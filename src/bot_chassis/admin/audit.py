"""Лог действий администрации в канал audit_chat_id. Сбой отправки команду не роняет."""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from ..config import BotChassisConfig


async def send_admin_audit(
    bot: Bot | None,
    config: BotChassisConfig,
    text: str,
    is_html: bool = False,
) -> None:
    """Отправить строку аудита. При is_html=False текст экранируется здесь.

    При is_html=True вызывающий экранирует пользовательские поля сам.
    Ошибка парсера Telegram откатывается на экранированный текст.
    """
    chat_id = config.audit_chat_id
    if chat_id is None or bot is None:
        return
    payload = text if is_html else html.escape(text)
    try:
        try:
            await bot.send_message(chat_id, payload, parse_mode="HTML")
        except TelegramBadRequest:
            if not is_html:
                raise
            await bot.send_message(chat_id, html.escape(text), parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить аудит-лог")
