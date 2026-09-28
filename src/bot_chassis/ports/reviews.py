"""Внешний сток отзывов: модерация, публикация и публичная ссылка. Без содержимого в SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from ..service_notify import thread_kwargs


@dataclass(frozen=True, slots=True)
class ReviewPublishResult:
    chat_id: int
    message_id: int
    url: str


class ReviewSinkPort(Protocol):
    """Кузов задаёт очередь модерации и канал публикации."""

    async def copy_to_moderation(
        self,
        bot: Bot,
        *,
        header: str,
        markup: InlineKeyboardMarkup | None,
        source_chat_id: int,
        source_message_id: int,
    ) -> tuple[int, int]:
        """Копирует материал в закрытую очередь. Возвращает (chat_id, message_id карточки)."""

    async def publish(
        self,
        bot: Bot,
        *,
        source_chat_id: int,
        source_message_id: int,
    ) -> ReviewPublishResult:
        """Публикует оригинал в канал и возвращает ID поста и прямую ссылку."""


@dataclass(slots=True)
class TelegramReviewSink:
    """Штатный сток: закрытый чат модерации и публичный канал-портфолио."""

    moderation_chat_id: int
    channel_id: int
    channel_url: str
    moderation_thread_id: int | None = None
    channel_thread_id: int | None = None

    async def copy_to_moderation(
        self,
        bot: Bot,
        *,
        header: str,
        markup: InlineKeyboardMarkup | None,
        source_chat_id: int,
        source_message_id: int,
    ) -> tuple[int, int]:
        topic = thread_kwargs(self.moderation_thread_id)
        card = await bot.send_message(
            chat_id=self.moderation_chat_id,
            text=header,
            parse_mode="HTML",
            reply_markup=markup,
            **topic,
        )
        await bot.copy_message(
            chat_id=self.moderation_chat_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
            **topic,
        )
        return self.moderation_chat_id, card.message_id

    async def publish(
        self,
        bot: Bot,
        *,
        source_chat_id: int,
        source_message_id: int,
    ) -> ReviewPublishResult:
        topic = thread_kwargs(self.channel_thread_id)
        copied = await bot.copy_message(
            chat_id=self.channel_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
            **topic,
        )
        base = self.channel_url.rstrip("/")
        url = f"{base}/{copied.message_id}"
        return ReviewPublishResult(
            chat_id=self.channel_id,
            message_id=int(copied.message_id),
            url=url,
        )
