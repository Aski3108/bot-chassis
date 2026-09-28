"""Upsert профиля, кэш локали, тихий сброс тени и first-touch /start."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Update

from ..config import BotChassisConfig, resolved_origin
from ..localization import InitialLocalePolicy, resolve_initial_locale
from ..storage import Storage
from ..user_lifecycle import confirm_active_and_maybe_notify


class UserActivityMiddleware(BaseMiddleware):
    def __init__(
        self,
        bot_id: str,
        storage: Storage,
        config: BotChassisConfig,
        locale_cache: dict[int, str] | None = None,
        locale_policy: InitialLocalePolicy | None = None,
        locale_resolver: Callable[[str | None], str] | None = None,
        bot_display_name_provider=None,
    ) -> None:
        self._bot_id = bot_id
        self._storage = storage
        self._config = config
        self._locale_cache = locale_cache
        self._locale_policy = locale_policy or InitialLocalePolicy()
        self._locale_resolver = locale_resolver
        self._bot_display_name_provider = bot_display_name_provider

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        raw_language = user.language_code
        resolved = (
            self._locale_resolver(raw_language)
            if self._locale_resolver is not None
            else resolve_initial_locale(raw_language, self._locale_policy)
        )
        user_record = await self._storage.users.record_telegram_visit(
            self._bot_id,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            raw_language,
            resolved,
        )
        if self._locale_cache is not None and user_record:
            self._locale_cache[user.id] = user_record.language_code

        if isinstance(event, Update):
            await self._capture_start_payload(event, user.id)
        if _confirms_private_lifecycle(event):
            await self._confirm_lifecycle(data, user)

        if isinstance(event, Update) and user_record.is_shadow_banned:
            immune = await self._storage.roles.has_any_role(
                self._bot_id,
                user.id,
                ("admin", "superadmin"),
            )
            if not immune:
                if _is_membership_update(event) or _is_payment_update(event):
                    return await handler(event, data)
                if event.callback_query is not None:
                    await event.callback_query.answer()
                    return None
                return None

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

    async def _confirm_lifecycle(self, data: dict[str, Any], user) -> None:
        bot = data.get("bot")
        if bot is None:
            return
        profile = await self._storage.users.get_user(self._bot_id, user.id)
        if profile is None:
            return
        bot_name = resolved_origin(self._config)
        provider = self._bot_display_name_provider
        if provider is not None:
            named = provider(resolved_origin(self._config), int(bot.id))
            if inspect.isawaitable(named):
                named = await named
            if named:
                bot_name = str(named)
        await confirm_active_and_maybe_notify(
            self._storage,
            self._config,
            bot,
            user_id=user.id,
            username=profile.username,
            locale=profile.language_code,
            raw_language=profile.telegram_language_code,
            source=profile.traffic_source,
            telegram_bot_id=int(bot.id),
            bot_name=bot_name,
        )


def _is_membership_update(event: TelegramObject) -> bool:
    return isinstance(event, Update) and event.my_chat_member is not None


def _confirms_private_lifecycle(event: TelegramObject) -> bool:
    """Групповое сообщение не доказывает, что личный диалог с ботом жив."""
    if not isinstance(event, Update) or event.my_chat_member is not None:
        return False
    chat = None
    if event.message is not None:
        chat = event.message.chat
    elif event.edited_message is not None:
        chat = event.edited_message.chat
    elif event.callback_query is not None and event.callback_query.message is not None:
        chat = event.callback_query.message.chat
    if chat is None:
        return event.callback_query is not None or event.pre_checkout_query is not None
    return chat.type == ChatType.PRIVATE


def _is_payment_update(event: Update) -> bool:
    if event.pre_checkout_query is not None:
        return True
    return event.message is not None and event.message.successful_payment is not None
