"""Лог действий администрации в канал audit_chat_id. Сбой отправки команду не роняет."""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from ..config import BotChassisConfig
from ..service_notify import deliver_service_message, resolve_service_destination


async def send_admin_audit(
    bot: Bot | None,
    config: BotChassisConfig,
    text: str,
    is_html: bool = False,
) -> bool:
    """Отправить строку аудита и вернуть факт доставки.

    При is_html=False текст экранируется здесь.

    При is_html=True вызывающий экранирует пользовательские поля сам.
    Ошибка парсера Telegram откатывается на экранированный текст.
    """
    destination = resolve_service_destination(config, "audit")
    if destination is None or bot is None:
        return False
    payload = text if is_html else html.escape(text)
    try:
        try:
            await deliver_service_message(bot, destination, payload, parse_mode="HTML")
        except TelegramBadRequest:
            if not is_html:
                raise
            await deliver_service_message(bot, destination, html.escape(text), parse_mode="HTML")
        return True
    except Exception:
        logger.exception("Не удалось отправить аудит-лог")
        return False
