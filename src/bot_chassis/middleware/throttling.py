"""Скользящее окно 4 события/сек. pre_checkout и successful_payment не учитываются."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import TelegramObject, Update

_WINDOW_SECONDS = 1.0
_LIMIT = 4
_GC_INTERVAL_SECONDS = 60.0
_TOAST = "⚠️ Слишком часто! Пожалуйста, помедленнее."


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, bot_id: str, enabled: bool = True) -> None:
        self._bot_id = bot_id
        self._enabled = enabled
        self._hits: dict[tuple[str, int], list[float]] = {}
        self._last_gc = time.monotonic()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._enabled:
            return await handler(event, data)
        if isinstance(event, Update) and _is_payment_update(event):
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        key = (self._bot_id, user.id)
        fresh = [stamp for stamp in self._hits.get(key, ()) if now - stamp < _WINDOW_SECONDS]
        if fresh:
            self._hits[key] = fresh
        else:
            self._hits.pop(key, None)
        self._gc(now)

        current = self._hits.get(key, [])
        if len(current) >= _LIMIT:
            if isinstance(event, Update) and event.callback_query is not None:
                await event.callback_query.answer(_TOAST, show_alert=False)
            return None

        current.append(now)
        self._hits[key] = current
        return await handler(event, data)

    def _gc(self, now: float) -> None:
        if now - self._last_gc < _GC_INTERVAL_SECONDS:
            return
        self._last_gc = now
        alive: dict[tuple[str, int], list[float]] = {}
        for key, stamps in self._hits.items():
            fresh = [stamp for stamp in stamps if now - stamp < _WINDOW_SECONDS]
            if fresh:
                alive[key] = fresh
        self._hits = alive


def _is_payment_update(event: Update) -> bool:
    if event.pre_checkout_query is not None:
        return True
    return event.message is not None and event.message.successful_payment is not None
