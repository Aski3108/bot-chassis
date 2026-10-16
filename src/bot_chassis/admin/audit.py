"""Лог действий администрации в канал audit_chat_id. Сбой отправки команду не роняет."""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from ..config import BotChassisConfig
from ..service_notify import deliver_service_message, resolve_service_destination


def format_sanction_audit(
    action: str,
    *,
    target_id: int,
    target_username: str | None,
    actor_id: int,
    actor_username: str | None,
    reason: str | None = None,
) -> str:
    """Собрать безопасную HTML-карточку изменения санкции."""
    target_identity = html.escape(f"@{target_username}" if target_username else "без username")
    actor_identity = html.escape(f"@{actor_username}" if actor_username else "без username")
    common = (
        f"Пользователь: {target_identity} (ID: <code>{target_id}</code>)\n"
        f"Администратор: {actor_identity} (ID: <code>{actor_id}</code>)"
    )
    if action == "ban":
        return (
            "🚫 <b>Блокировка пользователя</b>\n\n"
            f"{common}\nТип санкции: <b>Полный бан</b>\n"
            f"Причина: <b>{html.escape(reason or 'Не указана')}</b>"
        )
    if action == "shadow_on":
        return (
            "👤🕶 <b>Теневой бан пользователя</b>\n\n"
            f"{common}\nТип санкции: <b>Теневой бан</b>\n"
            f"Причина: <b>{html.escape(reason or 'Не указана')}</b>"
        )
    if action == "unban":
        return "✅ <b>Пользователь разблокирован</b>\n\n" + common
    if action == "shadow_off":
        return "✅ <b>Теневой бан снят</b>\n\n" + common
    raise ValueError(f"Unknown sanction action: {action}")


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
