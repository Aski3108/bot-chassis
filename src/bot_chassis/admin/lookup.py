"""Ожидание поиска пользователя и причины санкции. Один PendingInputStore."""

from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import Message

from ..followup import PendingInput, PendingInputKind, PendingInputStore, PendingScope

FIND_PROMPT = """🔍 <b>Поиск пользователя</b>

Отправьте в чат @username или числовой ID пользователя.
Либо откройте полный список пользователей базы данных."""
FIND_CANCELLED = "Поиск отменён."
SANCTION_STALE = "Действие устарело"
SANCTION_TARGET_MISMATCH = "Это ожидание для другого пользователя"


def begin_admin_lookup(bot_id: str, actor_id: int, pending_store: PendingInputStore) -> None:
    del bot_id
    pending_store.set(
        actor_id,
        PendingInput(kind=PendingInputKind.ADMIN_LOOKUP),
        scope=PendingScope.ADMIN,
    )


def cancel_admin_lookup(bot_id: str, actor_id: int, pending_store: PendingInputStore) -> None:
    del bot_id
    pending_store.clear(actor_id, scope=PendingScope.ADMIN)


def admin_lookup_is_waiting(bot_id: str, actor_id: int, pending_store: PendingInputStore) -> bool:
    del bot_id
    return pending_store.is_active(
        actor_id,
        PendingInputKind.ADMIN_LOOKUP,
        scope=PendingScope.ADMIN,
    )


class AwaitingAdminLookup(Filter):
    def __init__(self, bot_id: str, pending_store: PendingInputStore) -> None:
        super().__init__()
        self._bot_id = bot_id
        self._pending = pending_store

    async def __call__(self, message: Message) -> bool:
        actor = message.from_user
        if actor is None or not admin_lookup_is_waiting(self._bot_id, actor.id, self._pending):
            return False
        from .broadcast import is_awaiting_broadcast_text

        if is_awaiting_broadcast_text(self._bot_id, actor.id):
            return False
        text = (message.text or "").strip()
        command = text.split(maxsplit=1)[0].split("@", 1)[0] if text.startswith("/") else ""
        if command and command != "/cancel":
            return False
        return True


class AwaitingAdminBanReason(Filter):
    def __init__(self, pending_store: PendingInputStore) -> None:
        super().__init__()
        self._pending = pending_store

    async def __call__(self, message: Message) -> bool:
        actor = message.from_user
        if actor is None:
            return False
        if (message.text or "").startswith("/"):
            return False
        return self._pending.get(
            actor.id,
            PendingInputKind.ADMIN_BAN_REASON,
            scope=PendingScope.ADMIN,
        ) is not None
