"""
BANDA — booking flow handlers (aiogram 3)

Oqim:
  /start yoki "Записаться" tugmasi
    -> xizmat(lar) tanlash (multi-select: bir nechta xizmatni belgilab,
       "Готово ✅" bosiladi — masalan Мужская стрижка + Борода combo)
    -> barber tanlash (Али/Владимир/Илья/Алексей alohida)
    -> narx va vaqt combo qoidalari asosida hisoblanadi
    -> sana tanlash
    -> vaqt tanlash (band bo'lmagan slotlar, 15 daqiqalik qadam)
    -> tasdiqlash ekrani -> "Подтвердить ✅"
    -> DB'ga yoziladi + barberga avtomatik xabar boradi

Bu faylni mavjud bot.py ichiga import qilib, dispatcher'ga router qo'shasan:
    from handlers import booking_router
    dp.include_router(booking_router)
"""
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db

booking_router = Router()


class BookingStates(StatesGroup):
    choosing_services = State()
    choosing_barber = State()
    choosing_date = State()
    choosing_time = State()
    confirming = State()


# ---------- KEYBOARDS ----------

def services_kb(selected_ids: set):
    """Multi-select: tanlangan xizmatlar oldida ✅ belgisi chiqadi."""
    kb = InlineKeyboardBuilder()
    for s in db.get_services():
        mark = "✅ " if s["id"] in selected_ids else ""
        kb.button(text=f"{mark}{s['name_ru']}", callback_data=f"svc:{s['id']}")
    kb.adjust(1)
    if selected_ids:
        kb.row(InlineKeyboardBuilder().button(
            text="Готово ✅", callback_data="services_done"
        ).as_markup().inline_keyboard[0][0])
    return kb.as_markup()


def barbers_kb():
    kb = InlineKeyboardBuilder()
    for b in db.get_barbers():
        kb.button(text=b["name"], callback_data=f"barber:{b['id']}")
    kb.adjust(2)
    return kb.as_markup()


def dates_kb():
    kb = InlineKeyboardBuilder()
    today = datetime.now()
    for i in range(7):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else d.strftime("%d.%m")
        kb.button(text=label, callback_data=f"date:{d.strftime('%Y-%m-%d')}")
    kb.adjust(3)
    return kb.as_markup()


def times_kb(slots):
    kb = InlineKeyboardBuilder()
    for t in slots:
        kb.button(text=t, callback_data=f"time:{t}")
    kb.adjust(4)
    return kb.as_markup()


def confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Подтвердить ✅", callback_data="confirm_yes")
    kb.button(text="Отменить ❌", callback_data="confirm_no")
    kb.adjust(1)
    return kb.as_markup()


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"


# ---------- HANDLERS ----------

@booking_router.message(Command("book"))
@booking_router.message(F.text == "Записаться")
async def start_booking(message: Message, state: FSMContext):
    if not db.get_client(message.from_user.id):
        await message.answer("Сначала нужно зарегистрироваться — нажмите /start")
        return

    await state.clear()
    await state.update_data(selected_services=[])
    await state.set_state(BookingStates.choosing_services)
    await message.answer(
        "Выберите услугу (можно несколько, например Стрижка + Борода):",
        reply_markup=services_kb(set()),
    )


@booking_router.callback_query(BookingStates.choosing_services, F.data.startswith("svc:"))
async def service_toggled(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_services", []))

    if service_id in selected:
        selected.remove(service_id)
    else:
        selected.add(service_id)

    await state.update_data(selected_services=list(selected))
    await callback.message.edit_reply_markup(reply_markup=services_kb(selected))
    await callback.answer()


@booking_router.callback_query(BookingStates.choosing_services, F.data == "services_done")
async def services_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_services", [])
    if not selected:
        await callback.answer("Сначала выберите хотя бы одну услугу", show_alert=True)
        return

    names = [db.get_service(sid)["name_ru"] for sid in selected]
    await state.set_state(BookingStates.choosing_barber)

    await callback.message.edit_text(
        f"Услуги: {', '.join(names)}\n\nВыберите мастера:",
        reply_markup=barbers_kb(),
    )
    await callback.answer()


@booking_router.callback_query(BookingStates.choosing_barber, F.data.startswith("barber:"))
async def barber_chosen(callback: CallbackQuery, state: FSMContext):
    barber_id = int(callback.data.split(":")[1])
    barber = db.get_barber(barber_id)
    data = await state.get_data()
    selected = data["selected_services"]

    duration, price = db.get_combo_duration_and_price(selected, barber_id)
    names = [db.get_service(sid)["name_ru"] for sid in selected]

    await state.update_data(
        barber_id=barber_id,
        barber_name=barber["name"],
        duration=duration,
        price=price,
        service_names=names,
    )
    await state.set_state(BookingStates.choosing_date)

    await callback.message.edit_text(
        f"Услуги: {', '.join(names)}\n"
        f"Мастер: {barber['name']}\n"
        f"Длительность: {format_duration(duration)}\n"
        f"Цена: {price}₽\n\n"
        f"Выберите день:",
        reply_markup=dates_kb(),
    )
    await callback.answer()


@booking_router.callback_query(BookingStates.choosing_date, F.data.startswith("date:"))
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":")[1]
    data = await state.get_data()

    slots = db.get_available_slots(data["barber_id"], data["duration"], date_str)
    if not slots:
        await callback.answer("На этот день нет свободных окон, выберите другой день", show_alert=True)
        return

    await state.update_data(date_str=date_str)
    await state.set_state(BookingStates.choosing_time)

    await callback.message.edit_text(
        f"Услуги: {', '.join(data['service_names'])}\n"
        f"Мастер: {data['barber_name']}\n"
        f"Дата: {date_str}\n\n"
        f"Выберите время:",
        reply_markup=times_kb(slots),
    )
    await callback.answer()


@booking_router.callback_query(BookingStates.choosing_time, F.data.startswith("time:"))
async def time_chosen(callback: CallbackQuery, state: FSMContext):
    time_str = callback.data.split(":", 1)[1]
    await state.update_data(time_str=time_str)
    await state.set_state(BookingStates.confirming)

    data = await state.get_data()
    text = (
        "Подтвердите запись:\n\n"
        f"Услуги: {', '.join(data['service_names'])}\n"
        f"Мастер: {data['barber_name']}\n"
        f"Дата: {data['date_str']}\n"
        f"Время: {time_str}\n"
        f"Длительность: {format_duration(data['duration'])}\n"
        f"Цена: {data['price']}₽"
    )
    await callback.message.edit_text(text, reply_markup=confirm_kb())
    await callback.answer()


@booking_router.callback_query(BookingStates.confirming, F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    client = callback.from_user

    booking_id = db.create_booking(
        client_tg_id=client.id,
        client_name=client.full_name,
        client_username=client.username,
        service_ids=data["selected_services"],
        barber_id=data["barber_id"],
        date_str=data["date_str"],
        time_str=data["time_str"],
        duration_min=data["duration"],
        price=data["price"],
    )

    await callback.message.edit_text(
        "Запись подтверждена! ✅\n\n"
        f"Услуги: {', '.join(data['service_names'])}\n"
        f"Мастер: {data['barber_name']}\n"
        f"Дата: {data['date_str']}\n"
        f"Время: {data['time_str']}\n"
        f"Цена: {data['price']}₽\n\n"
        "Ждём вас!"
    )
    await callback.answer("Готово!")

    # --- barberning shaxsiy kanaliga avtomatik xabar ---
    barber = db.get_barber(data["barber_id"])
    client_record = db.get_client(client.id)

    # shu kunda barberning qolgan bo'sh vaqtlarini ham ko'rsatamiz
    # (30 daqiqalik minimal xizmat granularity bo'yicha, umumiy tasavvur uchun)
    free_slots = db.get_available_slots(data["barber_id"], 30, data["date_str"])
    free_slots_text = ", ".join(free_slots) if free_slots else "свободных окон больше нет"

    notify_text = (
        "🔔 Новая запись!\n\n"
        f"Клиент: {client_record['full_name']}\n"
        f"Телефон: {client_record['phone']}\n"
        f"Услуги: {', '.join(data['service_names'])}\n"
        f"Дата: {data['date_str']}\n"
        f"Время: {data['time_str']}\n"
        f"Длительность: {format_duration(data['duration'])}\n"
        f"Цена: {data['price']}₽\n"
        f"ID записи: #{booking_id}\n\n"
        f"Свободные окна на {data['date_str']}: {free_slots_text}"
    )
    try:
        await bot.send_message(barber["channel_id"], notify_text)
    except Exception:
        # kanal ID noto'g'ri bo'lsa yoki bot kanalga admin qilib qo'yilmagan bo'lsa,
        # bu yerda log qilib qo'yish kerak (masalan logging.exception)
        pass

    await state.clear()


@booking_router.callback_query(BookingStates.confirming, F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Запись отменена. Чтобы начать заново — /book")
    await callback.answer()
