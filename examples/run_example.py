"""
Пример запуска Telegram-бота на базе bot_chassis (Суб-шасси 1: Кнопки).
Демонстрирует:
- регистрацию синей кнопки «Меню» в клиенте через register_button_chassis_startup(dp, bot)
- подключение роутера шасси (create_button_chassis_router)
- слот доменного ряда (domain_rows)
- порты Личного кабинета и раздела Info
- двусторонний мост поддержки.
"""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Добавляем путь src для локального импорта без pip install
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from bot_chassis import (
    create_button_chassis_router,
    register_button_chassis_startup,
    CardClosePolicy,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot_chassis_example")


async def demo_render_cabinet(message: types.Message, user_id: int, bot: Bot) -> types.Message:
    """Демо-колбэк кузова для отрисовки Кабинета."""
    return await message.answer(
        f"👤 <b>Личный кабинет (Кузов Демо)</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Статус: <i>Базовый</i>\n\n"
        f"<i>Здесь кузов выводит историю, тесты или баланс.</i>",
        parse_mode="HTML",
    )


async def demo_render_info(message: types.Message, user_id: int, bot: Bot) -> types.Message:
    """Демо-колбэк кузова для отрисовки раздела Info."""
    return await message.answer(
        f"ℹ️ <b>О проекте (Кузов Демо)</b>\n\n"
        f"Универсальное модульное шасси Telegram-бота.\n"
        f"Раздел наполняется прикладным ботом.",
        parse_mode="HTML",
    )


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не задан! Задайте переменную окружения BOT_TOKEN.")
        logger.info("Для теста скопируйте examples/.env.example в .env")
        return

    support_chat_id_raw = os.getenv("SUPPORT_CHAT_ID", "0")
    support_chat_id = int(support_chat_id_raw) if support_chat_id_raw.lstrip("-").isdigit() else None

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 1. Регистрация синей кнопки [Меню] в клиенте Telegram на старте
    register_button_chassis_startup(dp, bot)

    # 2. Подключение роутера кнопочного шасси
    chassis_router = create_button_chassis_router(
        support_chat_id=support_chat_id,
        enable_cabinet=True,
        enable_info=True,
        enable_support=True,
        render_cabinet_callback=demo_render_cabinet,
        render_info_callback=demo_render_info,
        cabinet_close_policy=CardClosePolicy.DELETE,
        domain_rows=[["📊 Ваши задачи", "🔍 Поиск"]],
        project_label="Демо Бот (Шасси)",
    )
    dp.include_router(chassis_router)

    logger.info("Бот успешно запущен на базе bot-chassis. Нажмите Ctrl+C для остановки.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
