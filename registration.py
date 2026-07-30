"""
BANDA — ro'yxatdan o'tish (registratsiya) oqimi

Klient birinchi marta /start bosganda:
  1. Ism so'raladi
  2. Telefon raqami so'raladi (tugma orqali ulashish yoki qo'lda yozish)
  3. clients jadvaliga yoziladi
  4. "Записаться" tugmasi bilan asosiy menyu ochiladi

Agar klient avval ro'yxatdan o'tgan bo'lsa, /start to'g'ridan-to'g'ri
asosiy menyuni ko'rsatadi (qayta ro'yxatdan o'tkazmaydi).
"""
import re

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

import db

registration_router = Router()

PHONE_RE = re.compile(r"^\+?\d{9,15}$")


class RegistrationStates(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Записаться")]],
        resize_keyboard=True,
    )


@registration_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    client = db.get_client(message.from_user.id)
    if client:
        await message.answer(
            f"С возвращением, {client['full_name']}! 👋",
            reply_markup=main_menu_kb(),
        )
        return

    await state.set_state(RegistrationStates.waiting_name)
    await message.answer(
        "Добро пожаловать в BANDA! 💈\n\n"
        "Для записи сначала нужно зарегистрироваться.\n"
        "Как вас зовут?",
        reply_markup=ReplyKeyboardRemove(),
    )


@registration_router.message(RegistrationStates.waiting_name)
async def name_received(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Пожалуйста, введите имя корректно:")
        return

    await state.update_data(full_name=name)
    await state.set_state(RegistrationStates.waiting_phone)
    await message.answer(
        f"Приятно познакомиться, {name}!\n\n"
        "Теперь отправьте номер телефона (кнопкой ниже или вручную, например +79991234567):",
        reply_markup=contact_kb(),
    )


@registration_router.message(RegistrationStates.waiting_phone, F.contact)
async def phone_received_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    data = await state.get_data()
    db.create_or_update_client(message.from_user.id, data["full_name"], phone)
    await state.clear()

    await message.answer(
        "Регистрация завершена ✅\n\nТеперь можно записаться на услугу:",
        reply_markup=main_menu_kb(),
    )


@registration_router.message(RegistrationStates.waiting_phone, F.text)
async def phone_received_text(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "").replace("-", "")
    if not PHONE_RE.match(phone):
        await message.answer(
            "Похоже, номер введён некорректно. Попробуйте ещё раз "
            "(например +79991234567) или нажмите кнопку ниже:",
            reply_markup=contact_kb(),
        )
        return

    data = await state.get_data()
    db.create_or_update_client(message.from_user.id, data["full_name"], phone)
    await state.clear()

    await message.answer(
        "Регистрация завершена ✅\n\nТеперь можно записаться на услугу:",
        reply_markup=main_menu_kb(),
    )
