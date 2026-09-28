"""Gate 5C: отзывы, согласие, модерация, публикация без содержимого в SQLite."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    Message,
    PhotoSize,
    Update,
    User,
)

from bot_chassis.config import BotChassisConfig
from bot_chassis.contracts import BTN_SUPPORT_RU
from bot_chassis.factory import create_complete_chassis
from bot_chassis.followup import PendingInputKind
from bot_chassis.ports.reviews import ReviewPublishResult, TelegramReviewSink


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name in {"SendMessage", "EditMessageText", "CopyMessage"}:
            return Message(
                message_id=getattr(method, "message_id", None) or len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0) or 7, type="private"),
                text=getattr(method, "text", "") or "",
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _user(user_id: int, first_name: str = "N") -> User:
    return User(id=user_id, is_bot=False, first_name=first_name)


@dataclass
class _FakeSink:
    fail_publish: bool = False
    moderation: list = field(default_factory=list)
    published: list = field(default_factory=list)

    async def copy_to_moderation(self, bot, **kwargs):
        self.moderation.append(kwargs)
        sent = await bot.send_message(
            chat_id=-200,
            text=kwargs["header"],
            reply_markup=kwargs.get("markup"),
        )
        return -200, sent.message_id

    async def publish(self, bot, **kwargs):
        if self.fail_publish:
            raise RuntimeError("channel down")
        self.published.append(kwargs)
        return ReviewPublishResult(-300, 77, "https://t.me/example_reviews/77")


class TestGate5CReviews(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "reviews.db")
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.sink = _FakeSink()

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def _chassis(self, sink=None, superadmin_ids=(14,)):
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=superadmin_ids,
            support_chat_id=-100,
            enable_admin=True,
            enable_payments=False,
            enable_throttling=False,
        )
        return await create_complete_chassis(
            self.bot,
            config,
            review_sink=sink if sink is not None else self.sink,
        )

    async def _message(self, chassis, user_id: int, text: str | None, update_id: int, **extra) -> None:
        kwargs = dict(
            message_id=update_id,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=_user(user_id),
        )
        if text is not None:
            kwargs["text"] = text
        kwargs.update(extra)
        await chassis.dp.feed_update(
            self.bot,
            Update(update_id=update_id, message=Message(**kwargs)),
        )

    async def _callback(self, chassis, user_id: int, data: str, update_id: int, chat_id: int | None = None) -> None:
        panel = Message(
            message_id=40,
            date=1,
            chat=Chat(id=chat_id or user_id, type="private"),
            from_user=_user(user_id),
            text="card",
        )
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=str(update_id),
                    from_user=_user(user_id),
                    chat_instance="x",
                    data=data,
                    message=panel,
                ),
            ),
        )

    def _texts(self) -> list[str]:
        return [
            item.text
            for item in self.session.requests
            if item.__class__.__name__ in {"SendMessage", "EditMessageText"}
            and getattr(item, "text", None)
        ]

    def _callbacks_containing(self, text_part: str) -> list[str]:
        for item in reversed(self.session.requests):
            if item.__class__.__name__ not in {"SendMessage", "EditMessageText"}:
                continue
            if text_part not in (getattr(item, "text", "") or ""):
                continue
            markup = getattr(item, "reply_markup", None)
            if markup is None:
                continue
            return [button.callback_data for row in markup.inline_keyboard for button in row]
        return []

    async def test_button_hidden_without_sink(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            enable_throttling=False,
        )
        chassis = await create_complete_chassis(self.bot, config)
        await self._message(chassis, 7, BTN_SUPPORT_RU, 1)
        self.assertNotIn("core_sup:review", self._callbacks_containing("Выберите действие"))

    async def test_text_media_caption_consent_refuse_and_publish(self) -> None:
        chassis = await self._chassis()
        await self._message(chassis, 7, BTN_SUPPORT_RU, 1)
        self.assertIn("core_sup:review", self._callbacks_containing("Выберите действие"))
        await self._callback(chassis, 7, "core_sup:review", 2)
        self.assertTrue(chassis.pending_store.is_active(7, PendingInputKind.REVIEW))

        await self._message(chassis, 7, "отличный бот", 3)
        self.assertTrue(chassis.pending_store.is_active(7, PendingInputKind.REVIEW_CONSENT))
        self.assertIn("core_rev:yes", self._callbacks_containing("опубликовать"))
        await self._callback(chassis, 7, "core_rev:no", 4)
        rows = await chassis.storage.engine.run(
            lambda conn: conn.execute("SELECT COUNT(*) FROM review_submissions").fetchone()[0]
        )
        self.assertEqual(rows, 0)
        self.assertEqual(self.sink.moderation, [])
        self.assertTrue(any("нет согласия" in text.lower() for text in self._texts()))

        await self._callback(chassis, 7, "core_sup:review", 5)
        photo = [
            PhotoSize(file_id="p", file_unique_id="u", width=10, height=10, file_size=1)
        ]
        await self._message(chassis, 7, None, 6, photo=photo, caption="подпись")
        await self._callback(chassis, 7, "core_rev:yes", 7)
        self.assertEqual(len(self.sink.moderation), 1)
        record = await chassis.storage.engine.run(
            lambda conn: dict(conn.execute("SELECT * FROM review_submissions").fetchone())
        )
        self.assertEqual(record["status"], "pending")
        self.assertEqual(int(record["consent_to_publish"]), 1)
        self.assertNotIn("text", record)
        self.assertNotIn("body", record)
        review_id = record["review_id"]
        self.assertIn(f"core_rev:pub:{review_id}", self._callbacks_containing("Отзыв на модерацию"))

        await self._callback(chassis, 7, "core_sup:review", 8)
        await self._message(chassis, 7, "ещё текст", 9)
        await self._callback(chassis, 7, "core_rev:yes", 10)
        second = await chassis.storage.engine.run(
            lambda conn: conn.execute("SELECT COUNT(*) FROM review_submissions").fetchone()[0]
        )
        self.assertEqual(second, 2)

        document = Document(file_id="d", file_unique_id="du")
        await self._callback(chassis, 7, "core_sup:review", 11)
        await self._message(chassis, 7, None, 12, document=document)
        await self._callback(chassis, 7, "core_rev:yes", 13)
        self.assertEqual(len(self.sink.moderation), 3)

        await self._callback(chassis, 14, f"core_rev:pub:{review_id}", 14, chat_id=-200)
        self.assertEqual(len(self.sink.published), 1)
        published = await chassis.storage.reviews.get("bot_a", review_id)
        self.assertEqual(published.status, "published")
        self.assertEqual(published.published_message_id, 77)
        self.assertTrue(any("https://t.me/example_reviews/77" in text for text in self._texts()))

        await self._callback(chassis, 14, f"core_rev:pub:{review_id}", 15, chat_id=-200)
        self.assertEqual(len(self.sink.published), 1)

    async def test_reject_staff_blocked_and_publish_error(self) -> None:
        chassis = await self._chassis()
        await self._callback(chassis, 7, "core_sup:review", 1)
        await self._message(chassis, 7, "отзыв", 2)
        await self._callback(chassis, 7, "core_rev:yes", 3)
        review_id = (await chassis.storage.engine.run(
            lambda conn: conn.execute("SELECT review_id FROM review_submissions").fetchone()[0]
        ))
        await self._callback(chassis, 7, f"core_rev:rej:{review_id}", 4, chat_id=-200)
        still = await chassis.storage.reviews.get("bot_a", review_id)
        self.assertEqual(still.status, "pending")

        await self._callback(chassis, 14, f"core_rev:rej:{review_id}", 5, chat_id=-200)
        rejected = await chassis.storage.reviews.get("bot_a", review_id)
        self.assertEqual(rejected.status, "rejected")
        await self._callback(chassis, 14, f"core_rev:pub:{review_id}", 6, chat_id=-200)
        self.assertEqual(self.sink.published, [])

        await self._callback(chassis, 7, "core_sup:review", 7)
        await self._message(chassis, 7, "второй", 8)
        await self._callback(chassis, 7, "core_rev:yes", 9)
        other_id = (await chassis.storage.engine.run(
            lambda conn: conn.execute(
                "SELECT review_id FROM review_submissions WHERE status = 'pending'"
            ).fetchone()[0]
        ))
        self.sink.fail_publish = True
        await self._callback(chassis, 14, f"core_rev:pub:{other_id}", 10, chat_id=-200)
        pending = await chassis.storage.reviews.get("bot_a", other_id)
        self.assertEqual(pending.status, "pending")
        self.sink.fail_publish = False
        await self._callback(chassis, 14, f"core_rev:pub:{other_id}", 11, chat_id=-200)
        published = await chassis.storage.reviews.get("bot_a", other_id)
        self.assertEqual(published.status, "published")

    async def test_default_sink_builds_channel_url(self) -> None:
        sink = TelegramReviewSink(
            moderation_chat_id=-200,
            channel_id=-300,
            channel_url="https://t.me/example_reviews/",
        )
        bot = SimpleNamespace()

        async def copy_message(**kwargs):
            return SimpleNamespace(message_id=88)

        bot.copy_message = copy_message
        result = await sink.publish(bot, source_chat_id=7, source_message_id=3)
        self.assertEqual(result.url, "https://t.me/example_reviews/88")
        self.assertEqual(result.chat_id, -300)


if __name__ == "__main__":
    unittest.main()
