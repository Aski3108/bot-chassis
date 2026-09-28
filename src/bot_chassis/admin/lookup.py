"""Ожидание поиска пользователя. Не делит слот с поддержкой, рассылкой и кузовом."""

from __future__ import annotations

import time

from aiogram.filters import Filter
from aiogram.types import Message

from ..followup import PendingInput, PendingInputKind, PendingInputStore, PendingScope

_WAITING: dict[tuple[str, int], float] = {}
_TTL_SECONDS = 900.0

FIND_PROMPT = "Пришлите ID или @username."
FIND_CANCELLED = "Поиск отменён."


def begin_admin_lookup(
    bot_id: str,
    actor_id: int,
    pending_store: PendingInputStore | None = None,
) -> None:
    if pending_store is not None:
        pending_store.set(
            actor_id,
            PendingInput(kind=PendingInputKind.ADMIN_LOOKUP),
            scope=PendingScope.ADMIN,
        )
        return
    _WAITING[(bot_id, actor_id)] = time.time()


def cancel_admin_lookup(
    bot_id: str,
    actor_id: int,
    pending_store: PendingInputStore | None = None,
) -> None:
    if pending_store is not None:
        pending_store.clear(actor_id, scope=PendingScope.ADMIN)
        return
    _WAITING.pop((bot_id, actor_id), None)


def admin_lookup_is_waiting(
    bot_id: str,
    actor_id: int,
    pending_store: PendingInputStore | None = None,
) -> bool:
    if pending_store is not None:
        return pending_store.is_active(
            actor_id,
            PendingInputKind.ADMIN_LOOKUP,
            scope=PendingScope.ADMIN,
        )
    key = (bot_id, actor_id)
    started = _WAITING.get(key)
    if started is None:
        return False
    if time.time() - started > _TTL_SECONDS:
        _WAITING.pop(key, None)
        return False
    return True


def reset_admin_lookups() -> None:
    _WAITING.clear()


class AwaitingAdminLookup(Filter):
    def __init__(self, bot_id: str, pending_store: PendingInputStore | None = None) -> None:
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
