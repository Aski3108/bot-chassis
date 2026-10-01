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

_RESERVED_COMMANDS = frozenset({"menu", "start", "help", "support"})


async def setup_bot_commands(
    bot: Bot,
    custom_commands: Optional[Sequence[BotCommand]] = None,
) -> None:
    """
    Регистрирует список команд в Telegram Bot API.
    Порядок: /start сверху, доменные кузова в середине, /menu внизу.
    Один набор с двуязычными подписями; language_code не используется.
    """
    head = [BotCommand(command="start", description="Старт / Start")]
    middle: list[BotCommand] = []
    seen: set[str] = set()
    if custom_commands:
        for cmd in custom_commands:
            command_name = cmd.command.lstrip("/").casefold()
            if command_name in _RESERVED_COMMANDS:
                continue
            if command_name in seen:
                continue
            seen.add(command_name)
            middle.append(cmd)
    tail = [BotCommand(command="menu", description="Меню / Menu")]
    commands = head + middle + tail
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
