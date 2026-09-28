"""Жизненный цикл пользователя в одном Telegram-боте и ошибки доставки."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram import Dispatcher
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ChatMemberUpdated
from loguru import logger

from .config import BotChassisConfig, resolved_origin
from .service_notify import deliver_service_message, resolve_service_destination
from .storage import Storage

CANON_ALLOWED_UPDATES = (
    "message",
    "callback_query",
    "pre_checkout_query",
    "my_chat_member",
)

_ACTIVE_MEMBER = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.RESTRICTED,
}

STATUS_LABELS = {
    "active": "активен",
    "stopped": "остановлен пользователем",
    "deleted": "удалён",
}


def warn_if_my_chat_member_missing(allowed_updates: Sequence[str] | None) -> None:
    """Узкий список кузова без my_chat_member не даст мгновенный stopped."""
    if allowed_updates is None:
        return
    if "my_chat_member" not in allowed_updates:
        logger.warning(
            "allowed_updates не содержит my_chat_member: "
            "мгновенный статус stopped по блокировке работать не будет"
        )


def classify_delivery_error(exc: BaseException) -> str | None:
    """stopped / deleted для достоверной ошибки. Временная ошибка — None."""
    if isinstance(exc, TelegramRetryAfter):
        return None
    text = str(exc).casefold()
    if "deactivated" in text:
        return "deleted"
    if isinstance(exc, TelegramForbiddenError) and "blocked" in text:
        return "stopped"
    return None


def format_first_launch(
    *,
    username: str | None,
    user_id: int,
    bot_name: str,
    source: str | None,
    locale: str,
    raw_language: str | None,
) -> str:
    nick = f"@{username}" if username else "—"
    return (
        "Новый пользователь\n"
        f"{nick} · ID {user_id}\n"
        f"Бот: {bot_name}\n"
        f"Источник: {source or '—'}\n"
        f"Локаль: {locale}\n"
        f"language_code: {raw_language or '—'}"
    )


def register_membership_handler(dp: Dispatcher, storage: Storage, config: BotChassisConfig) -> None:
    async def _on_my_chat_member(event: ChatMemberUpdated) -> None:
        await apply_my_chat_member(storage, config, event)

    dp.my_chat_member.register(_on_my_chat_member)


async def apply_my_chat_member(storage: Storage, config: BotChassisConfig, event: ChatMemberUpdated) -> None:
    if event.chat.type != ChatType.PRIVATE:
        return
    actor = event.from_user
    if actor is None:
        return
    telegram_bot_id = _event_bot_id(event, storage)
    if telegram_bot_id is None:
        return
    origin = resolved_origin(config)
    status = event.new_chat_member.status
    if status == ChatMemberStatus.KICKED:
        await storage.bot_statuses.mark_stopped(
            config.bot_id,
            actor.id,
            origin,
            telegram_bot_id,
            "kicked",
        )
        return
    if status in _ACTIVE_MEMBER:
        await storage.bot_statuses.mark_active(config.bot_id, actor.id, origin, telegram_bot_id)


async def confirm_active_and_maybe_notify(
    storage: Storage,
    config: BotChassisConfig,
    bot,
    *,
    user_id: int,
    username: str | None,
    locale: str,
    raw_language: str | None,
    source: str | None,
    telegram_bot_id: int,
    bot_name: str,
) -> None:
    first = await storage.bot_statuses.mark_active(
        config.bot_id,
        user_id,
        resolved_origin(config),
        telegram_bot_id,
    )
    if not first or bot is None:
        return
    text = format_first_launch(
        username=username,
        user_id=user_id,
        bot_name=bot_name,
        source=source,
        locale=locale,
        raw_language=raw_language,
    )
    try:
        await deliver_service_message(bot, resolve_service_destination(config, "events"), text)
    except Exception:
        logger.exception(f"Событие первого запуска не отправлено user_id={user_id}")


async def record_delivery_outcome(
    storage: Storage,
    config: BotChassisConfig,
    *,
    user_id: int,
    telegram_bot_id: int,
    outcome: str,
) -> None:
    origin = resolved_origin(config)
    if outcome == "deleted":
        await storage.bot_statuses.mark_deleted(config.bot_id, user_id, origin, telegram_bot_id)
    elif outcome == "stopped":
        await storage.bot_statuses.mark_stopped(
            config.bot_id,
            user_id,
            origin,
            telegram_bot_id,
            "blocked",
        )


def _event_bot_id(event: ChatMemberUpdated, storage: Storage) -> int | None:
    bot = getattr(event, "bot", None)
    if bot is not None:
        return int(bot.id)
    process = storage.bot_statuses.process
    if process is None:
        return None
    return process.telegram_bot_id
