"""Upsert профиля, кэш локали, тихий сброс тени и first-touch /start."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import TelegramObject, Update

from ..config import BotChassisConfig
from ..storage import Storage


class UserActivityMiddleware(BaseMiddleware):
    def __init__(
        self,
        bot_id: str,
        storage: Storage,
        config: BotChassisConfig,
        locale_cache: dict[int, str] | None = None,
    ) -> None:
        self._bot_id = bot_id
        self._storage = storage
        self._config = config
        self._locale_cache = locale_cache

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        user_record = await self._storage.users.upsert_user(
            self._bot_id,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            user.language_code,
        )
        if self._locale_cache is not None and user_record:
            self._locale_cache[user.id] = user_record.language_code

        if isinstance(event, Update) and user_record.is_shadow_banned:
            immune = await self._storage.roles.has_any_role(
                self._bot_id,
                user.id,
                ("admin", "superadmin"),
            )
            if not immune:
                if _is_payment_update(event):
                    return await handler(event, data)
                if event.callback_query is not None:
                    await event.callback_query.answer()
                    return None
                return None

        if isinstance(event, Update):
            await self._capture_start_payload(event, user.id)
        return await handler(event, data)

    async def _capture_start_payload(self, event: Update, user_id: int) -> None:
        text = (event.message.text or "") if event.message else ""
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@")[0] if parts else ""
        if cmd == "/start" and len(parts) > 1:
            payload = parts[1].strip()
            if payload:
                if payload.startswith("ref_"):
                    try:
                        referrer_id = int(payload[4:])
                    except ValueError:
                        referrer_id = None
                    if referrer_id is not None and self._config.enable_referrals:
                        await self._storage.referrals.record_referral(
                            self._bot_id,
                            referrer_id,
                            user_id,
                        )
                await self._storage.users.set_traffic_source(self._bot_id, user_id, payload)


def _is_payment_update(event: Update) -> bool:
    if event.pre_checkout_query is not None:
        return True
    return event.message is not None and event.message.successful_payment is not None
