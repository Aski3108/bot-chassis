"""Регистрация команд Telegram Bot API (Button Chassis).

Управляет системной синей кнопкой «Меню» в клиенте Telegram:
- Регистрирует команды через bot.set_my_commands().
- Предоставляет хук register_button_chassis_startup(dp, bot) для автоматического
  вызова при старте диспетчера aiogram v3.
"""

from __future__ import annotations
from typing import Optional, Sequence
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeDefault
from loguru import logger


async def setup_bot_commands(
    bot: Bot,
    custom_commands: Optional[Sequence[BotCommand]] = None,
) -> None:
    """
    Регистрирует список команд в Telegram Bot API.
    Гарантирует доступность синей кнопки «Меню» в клиенте Telegram для всех пользователей.
    """
    default_commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="menu", description="📱 Восстановить кнопки меню"),
        BotCommand(command="help", description="ℹ️ О сервисе и инструкция"),
        BotCommand(command="support", description="💬 Служба поддержки"),
    ]
    commands_map = {c.command: c for c in default_commands}
    if custom_commands:
        for cmd in custom_commands:
            commands_map[cmd.command] = cmd
    commands = list(commands_map.values())
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info(f"✅ Команды бота ({len(commands)}) успешно зарегистрированы через set_my_commands.")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось зарегистрировать команды через set_my_commands: {e}")


def register_button_chassis_startup(
    dp: Dispatcher,
    bot: Bot,
    custom_commands: Optional[Sequence[BotCommand]] = None,
) -> None:
    """
    Регистрирует вызов setup_bot_commands на хук запуска диспетчера aiogram v3.
    Гарантирует, что синяя кнопка «Меню» активируется при старте бота автоматически.
    """
    async def _on_startup() -> None:
        await setup_bot_commands(bot, custom_commands=custom_commands)

    dp.startup.register(_on_startup)
    logger.info("🔗 Хук setup_bot_commands успешно зарегистрирован в dp.startup.")
