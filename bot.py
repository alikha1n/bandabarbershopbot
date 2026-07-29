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
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from aiohttp import web

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("banda")

# ====== SOZLAMALAR ======
BOT_TOKEN = "8625656240:AAGpY7gHUVv37WuI8BaGWoh1S8puATtDRws"
ADMIN_ID = 7434706702

DB_PATH = "/opt/bandabot/banda.db"

# Har bir ustaning zapis kanali (chat_id).
# Kanal chat_id olish uchun: botni kanalga admin qilib qo'sh, keyin kanalga
# istalgan xabar yubor va https://api.telegram.org/bot<TOKEN>/getUpdates orqali
# "chat":{"id": -100...} qiymatini ko'r. Yoki @userinfobot ga forward qil.
MASTERS = {
    "ali": {"name": "Ali", "channel_id": None},        # <-- kanal id qo'y
    "vladimir": {"name": "Vladimir", "channel_id": None},  # <-- kanal id qo'y
    "ilya": {"name": "Ilya", "channel_id": None},      # <-- kanal id qo'y
    "aleksey": {"name": "Aleksey", "channel_id": None},    # <-- kanal id qo'y
}

WEB_APP_URL = "https://alikha1n.github.io/banda-app-/"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ====== DB ======
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


# ====== FSM: RO'YXATDAN O'TISH ======
class Registration(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    client = get_client(message.from_user.id)

    if client:
        await message.answer(
            f"Xush kelibsan, {client['name']}! 💈\n"
            f"Zapis qilish uchun pastdagi tugmani bos.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer(
        "Assalomu alaykum! BANDA barbershopga xush kelibsiz 💈\n\n"
        "Ro'yxatdan o'tish uchun ismingizni yozing:"
    )
    await state.set_state(Registration.waiting_name)


@dp.message(Registration.waiting_name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())

    phone_btn = KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)
    kb = ReplyKeyboardMarkup(keyboard=[[phone_btn]], resize_keyboard=True, one_time_keyboard=True)

    await message.answer(
        "Rahmat! Endi telefon raqamingizni yuboring (tugma orqali):",
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
        f"Ro'yxatdan muvaffaqiyatli o'tdingiz, {name}! ✅\n\n"
        f"Endi zapis qilish uchun ilovani oching.",
        reply_markup=ReplyKeyboardRemove(),
    )
    log.info(f"Yangi klent: {name} ({phone}) id={message.from_user.id} token={token}")


@dp.message(Registration.waiting_phone)
async def phone_not_shared(message: Message):
    await message.answer("Iltimos, raqamni faqat tugma orqali yuboring 📱")


# ====== USTA KANALIGA XABAR YUBORISH ======
async def notify_master(master_key: str, client_name: str, client_phone: str, service: str, date: str, time: str):
    master = MASTERS.get(master_key)
    if not master or not master["channel_id"]:
        log.warning(f"Kanal ulanmagan: {master_key}")
        return

    text = (
        f"📅 <b>Yangi zapis!</b>\n\n"
        f"👤 Klent: {client_name}\n"
        f"📱 Raqam: {client_phone}\n"
        f"✂️ Xizmat: {service}\n"
        f"🗓 Sana: {date}\n"
        f"⏰ Vaqt: {time}"
    )
    try:
        await bot.send_message(master["channel_id"], text, parse_mode="HTML")
    except Exception as e:
        log.error(f"Kanalga yuborishda xato ({master_key}): {e}")


# ====== MINI APP UCHUN API ======
async def api_book(request: web.Request):
    """
    Frontend (Mini App) shu endpointga POST qiladi:
    {
        "telegram_id": 123456789,
        "master": "ali",
        "service": "Soch olish",
        "date": "2026-08-01",
        "time": "14:00"
    }
    """
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


# ====== ISHGA TUSHIRISH ======
async def main():
    init_db()

    web_app = create_web_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    log.info("API server 8080-portda ishga tushdi")

    log.info("Bot polling boshlandi")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
