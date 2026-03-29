import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from config import API_TOKEN
from handlers import router
from database import conn
import handlers

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
dp.include_router(router)

async def main():
    me = await bot.get_me()
    handlers.BOT_USERNAME = me.username
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню")
    ])
    print(f"🤖 Бот запущен! (@{handlers.BOT_USERNAME})")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        conn.close()
