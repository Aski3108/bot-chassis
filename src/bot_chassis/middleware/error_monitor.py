"""Перехват необработанных исключений на Update: ответ пользователю и алерт в саппорт."""

from __future__ import annotations

import html
import traceback
from typing import Any, Awaitable, Callable

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import TelegramObject, Update
from loguru import logger

from ..config import BotChassisConfig, resolved_alert_chat_id

_USER_ERROR = "⚠️ Произошла непредвиденная ошибка. Мы уже разбираемся!"
_PAYMENT_ERROR = "⚠️ Ошибка при обработке платежа."


class ErrorAlertMiddleware(BaseMiddleware):
    def __init__(self, config: BotChassisConfig) -> None:
        self._config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._config.enable_error_alerts:
            return await handler(event, data)
        try:
            return await handler(event, data)
        except Exception:
            escaped = html.escape(traceback.format_exc()[-3500:])
            await self._reply_to_user(event)
            await self._alert_support(data, escaped)
            return None

    async def _reply_to_user(self, event: TelegramObject) -> None:
        if not isinstance(event, Update):
            return
        try:
            if event.pre_checkout_query is not None:
                await event.pre_checkout_query.answer(ok=False, error_message=_PAYMENT_ERROR)
            elif event.callback_query is not None:
                await event.callback_query.answer(_USER_ERROR, show_alert=True)
            elif event.message is not None:
                await event.message.answer(_USER_ERROR)
        except Exception:
            logger.exception("Не удалось сообщить пользователю об ошибке шасси")

    async def _alert_support(self, data: dict[str, Any], escaped_traceback: str) -> None:
        chat_id = resolved_alert_chat_id(self._config)
        bot = data.get("bot")
        if chat_id is None or bot is None:
            return
        try:
            await bot.send_message(
                chat_id,
                f"⚠️ <b>Ошибка шасси</b>\n<pre>{escaped_traceback}</pre>",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Не удалось отправить алерт об ошибке в чат поддержки")
