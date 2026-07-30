"""
BANDA — asosiy ishga tushuvchi fayl.

Ishga tushirish:
    python3 bot.py

Deploy qilishda o'zingdagi odatdagi workflow: GitHub'ga shu nom bilan
(bot.py) push qilasan, serverda:
    curl -o /opt/banda/bot.py https://raw.githubusercontent.com/.../bot.py
    systemctl restart banda-bot
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import db
from registration import registration_router
from handlers import booking_router

# TODO: xavfsizlik uchun tavsiya — tokenni environment variable orqali
# saqlash (masalan: os.environ["BOT_TOKEN"]), lekin joriy iPhone/Termius
# workflow'ingga mos ravishda hozircha shu yerda to'g'ridan-to'g'ri turibdi.
BOT_TOKEN = "8625656240:AAGpY7gHUVv37WuI8BaGWoh1S8puATtDRws"

# Jigarning shaxsiy Telegram ID'si — hozircha barcha barberlar kanali
# o'rniga test sifatida shu ID ishlatilyapti (db.py da DEFAULT_TEST_CHANNEL_ID)
ADMIN_ID = 7434706702

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    db.init_db()
    logger.info("Database initialized.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(registration_router)
    dp.include_router(booking_router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot polling started.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
