"""
Пример запуска Telegram-бота на базе bot-chassis.
Демонстрирует инициализацию, установку постоянного синего меню,
подключение роутера шасси и обработку событий.
"""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Добавляем путь src для локального импорта без pip install
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from bot_chassis import (
    create_bot_chassis_router,
    setup_bot_commands,
    notify_admins_on_startup,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot_chassis_example")


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не задан! Задайте переменную окружения BOT_TOKEN.")
        logger.info("Для теста скопируйте examples/.env.example в .env")
        return

    support_chat_id_raw = os.getenv("SUPPORT_CHAT_ID", "0")
    support_chat_id = int(support_chat_id_raw) if support_chat_id_raw.lstrip("-").isdigit() else 0

    admin_ids_raw = os.getenv("ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip().isdigit()]

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 1. Регистрация синей кнопки [Меню] в клиенте Telegram
    await setup_bot_commands(bot)

    # 2. Подключение универсального роутера шасси
    chassis_router = create_bot_chassis_router(
        support_chat_id=support_chat_id,
        project_name="Demo Bot",
        support_project_label="Демо Бот (Шасси)",
    )
    dp.include_router(chassis_router)

    # 3. Оповещение администраторов о старте (если заданы)
    if admin_ids:
        await notify_admins_on_startup(bot, admin_ids, project_name="Demo Bot")

    logger.info("Бот успешно запущен на базе bot-chassis. Нажмите Ctrl+C для остановки.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
