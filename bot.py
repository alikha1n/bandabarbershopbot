import asyncio
import logging
import secrets
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from aiohttp import web

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("banda")

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "8625656240:AAGpY7gHUVv37WuI8BaGWoh1S8puATtDRws"
ADMIN_ID = 7434706702

DB_PATH = "/opt/banda/banda.db"

MASTERS = {
    "ali": {"name": "Ali", "channel_id": None},
    "vladimir": {"name": "Vladimir", "channel_id": None},
    "ilya": {"name": "Ilya", "channel_id": None},
    "aleksey": {"name": "Aleksey", "channel_id": None},
}

WEB_APP_URL = "https://alikha1n.github.io/banda-app-/"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def booking_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✂️ Записаться", web_app=WebAppInfo(url=WEB_APP_URL))]],
        resize_keyboard=True,
    )


# ====== БАЗА ДАННЫХ ======
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            telegram_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            registered_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            master_key TEXT NOT NULL,
            service TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (telegram_id) REFERENCES clients (telegram_id)
        )
        """
    )
    conn.commit()
    conn.close()


def get_client(telegram_id: int):
    conn = db()
    row = conn.execute(
        "SELECT * FROM clients WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


def create_client(telegram_id: int, name: str, phone: str) -> str:
    token = secrets.token_hex(16)
    conn = db()
    conn.execute(
        "INSERT INTO clients (telegram_id, name, phone, token, registered_at) VALUES (?, ?, ?, ?, ?)",
        (telegram_id, name, phone, token, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def save_booking(telegram_id: int, master_key: str, service: str, date: str, time: str):
    conn = db()
    conn.execute(
        "INSERT INTO bookings (telegram_id, master_key, service, date, time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (telegram_id, master_key, service, date, time, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ====== FSM: РЕГИСТРАЦИЯ ======
class Registration(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    client = get_client(message.from_user.id)

    if client:
        await message.answer(
            f"С возвращением, {client['name']}! 💈\n"
            f"Нажмите кнопку ниже, чтобы записаться.",
            reply_markup=booking_keyboard(),
        )
        return

    await message.answer(
        "Добро пожаловать в BANDA barbershop 💈\n\n"
        "Для регистрации напишите ваше имя:"
    )
    await state.set_state(Registration.waiting_name)


@dp.message(Registration.waiting_name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())

    phone_btn = KeyboardButton(text="📱 Отправить номер", request_contact=True)
    kb = ReplyKeyboardMarkup(keyboard=[[phone_btn]], resize_keyboard=True, one_time_keyboard=True)

    await message.answer(
        "Спасибо! Теперь отправьте номер телефона (кнопкой ниже):",
        reply_markup=kb,
    )
    await state.set_state(Registration.waiting_phone)


@dp.message(Registration.waiting_phone, F.contact)
async def get_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data["name"]
    phone = message.contact.phone_number

    token = create_client(message.from_user.id, name, phone)
    await state.clear()

    await message.answer(
        f"Регистрация прошла успешно, {name}! ✅\n\n"
        f"Теперь нажмите кнопку ниже, чтобы записаться.",
        reply_markup=booking_keyboard(),
    )
    log.info(f"Новый клиент: {name} ({phone}) id={message.from_user.id} token={token}")


@dp.message(Registration.waiting_phone)
async def phone_not_shared(message: Message):
    await message.answer("Пожалуйста, отправьте номер только через кнопку 📱")


# ====== УВЕДОМЛЕНИЕ МАСТЕРА ======
async def notify_master(master_key: str, client_name: str, client_phone: str, service: str, date: str, time: str):
    master = MASTERS.get(master_key)
    if not master or not master["channel_id"]:
        log.warning(f"Канал не привязан: {master_key}")
        return

    text = (
        f"📅 <b>Новая запись!</b>\n\n"
        f"👤 Клиент: {client_name}\n"
        f"📱 Телефон: {client_phone}\n"
        f"✂️ Услуга: {service}\n"
        f"🗓 Дата: {date}\n"
        f"⏰ Время: {time}"
    )
    try:
        await bot.send_message(master["channel_id"], text, parse_mode="HTML")
    except Exception as e:
        log.error(f"Ошибка отправки в канал ({master_key}): {e}")


# ====== API ДЛЯ MINI APP ======
async def api_book(request: web.Request):
    try:
        data = await request.json()
        telegram_id = int(data["telegram_id"])
        master_key = data["master"]
        service = data["service"]
        date = data["date"]
        time = data["time"]
    except (KeyError, ValueError, TypeError):
        return web.json_response({"ok": False, "error": "invalid payload"}, status=400)

    client = get_client(telegram_id)
    if not client:
        return web.json_response({"ok": False, "error": "client not registered"}, status=404)

    if master_key not in MASTERS:
        return web.json_response({"ok": False, "error": "unknown master"}, status=400)

    save_booking(telegram_id, master_key, service, date, time)
    await notify_master(master_key, client["name"], client["phone"], service, date, time)

    return web.json_response({"ok": True})


async def api_health(request: web.Request):
    return web.json_response({"ok": True, "service": "banda-bot"})


def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/book", api_book)
    app.router.add_get("/api/health", api_health)
    return app


# ====== ЗАПУСК ======
async def main():
    init_db()

    web_app = create_web_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    log.info("API сервер запущен на порту 8080")

    log.info("Бот запущен, начат polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
