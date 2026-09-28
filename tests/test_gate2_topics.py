"""Gate 2: темы служебных чатов и ответ поддержки только из исходной темы."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot_chassis.config import BotChassisConfig
from bot_chassis.service_notify import (
    deliver_service_message,
    resolve_service_destination,
    thread_kwargs,
)
from bot_chassis.support_bridge import (
    SupportThreadStore,
    deliver_support_reply_to_user,
    send_user_report_to_support,
)


class TestServiceTopics(unittest.IsolatedAsyncioTestCase):
    def test_missing_thread_id_is_omitted(self) -> None:
        self.assertEqual(thread_kwargs(None), {})
        config = BotChassisConfig(bot_id="bot_a", support_chat_id=-100)
        destination = resolve_service_destination(config, "ops")
        self.assertEqual(destination.chat_id, -100)
        self.assertIsNone(destination.thread_id)

    def test_named_topics_and_legacy_fallback(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            support_chat_id=-100,
            audit_chat_id=-200,
            support_thread_id=11,
            audit_thread_id=22,
            ops_thread_id=33,
            events_thread_id=44,
        )
        self.assertEqual(resolve_service_destination(config, "support").thread_id, 11)
        self.assertEqual(resolve_service_destination(config, "audit").chat_id, -200)
        self.assertEqual(resolve_service_destination(config, "payment").thread_id, 22)
        self.assertEqual(resolve_service_destination(config, "ops").thread_id, 33)
        self.assertEqual(resolve_service_destination(config, "events").thread_id, 44)

        legacy = BotChassisConfig(bot_id="bot_a", support_chat_id=-100, ops_thread_id=33)
        ops = resolve_service_destination(legacy, "ops")
        self.assertEqual((ops.chat_id, ops.thread_id), (-100, None))
        self.assertIsNone(resolve_service_destination(legacy, "payment").thread_id)
        self.assertIsNone(resolve_service_destination(legacy, "events").thread_id)
        self.assertIsNone(resolve_service_destination(legacy, "audit"))

    def test_seven_bots_share_one_group_with_separate_topics(self) -> None:
        seen = []
        for index in range(1, 8):
            config = BotChassisConfig(
                bot_id="network",
                origin_bot_id=f"bot-{index}",
                support_chat_id=-100,
                support_thread_id=1000 + index,
            )
            destination = resolve_service_destination(config, "support")
            seen.append((destination.chat_id, destination.thread_id))
        self.assertEqual(len({chat for chat, _thread in seen}), 1)
        self.assertEqual([thread for _chat, thread in seen], list(range(1001, 1008)))

    async def test_delivery_passes_thread_only_when_configured(self) -> None:
        bot = AsyncMock()
        general = BotChassisConfig(bot_id="bot_a", audit_chat_id=-200)
        await deliver_service_message(
            bot,
            resolve_service_destination(general, "ops"),
            "boom",
            parse_mode="HTML",
        )
        self.assertNotIn("message_thread_id", bot.send_message.await_args.kwargs)

        bot.send_message.reset_mock()
        forum = BotChassisConfig(bot_id="bot_a", audit_chat_id=-200, ops_thread_id=33)
        await deliver_service_message(
            bot,
            resolve_service_destination(forum, "ops"),
            "boom",
            parse_mode="HTML",
        )
        self.assertEqual(bot.send_message.await_args.kwargs["message_thread_id"], 33)
        self.assertEqual(bot.send_message.await_args.args[0], -200)

    async def test_support_copy_uses_the_same_topic(self) -> None:
        bot = AsyncMock()
        bot.send_message.return_value = SimpleNamespace(message_id=10)
        bot.copy_message.return_value = SimpleNamespace(message_id=11)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username="ann", full_name="Ann"),
            chat=SimpleNamespace(id=7),
            message_id=1,
        )
        store = SupportThreadStore(persistence_file=None)
        await send_user_report_to_support(
            bot,
            -100,
            user_message,
            store,
            message_thread_id=11,
        )
        self.assertEqual(bot.send_message.await_args.kwargs["message_thread_id"], 11)
        self.assertEqual(bot.copy_message.await_args.kwargs["message_thread_id"], 11)

        bot.send_message.reset_mock()
        bot.copy_message.reset_mock()
        await send_user_report_to_support(bot, -100, user_message, store)
        self.assertNotIn("message_thread_id", bot.send_message.await_args.kwargs)
        self.assertNotIn("message_thread_id", bot.copy_message.await_args.kwargs)

    async def test_reply_from_another_topic_is_ignored(self) -> None:
        store = SupportThreadStore(persistence_file=None)
        store.register(chat_id=-100, user_id=7, header_msg_id=10)
        reply = SimpleNamespace(
            reply_to_message=SimpleNamespace(message_id=10, message_thread_id=11),
            chat=SimpleNamespace(id=-100),
            message_thread_id=99,
            message_id=20,
        )
        bot = AsyncMock()
        bot.id = 1
        ok, status = await deliver_support_reply_to_user(
            bot,
            reply,
            store,
            expected_thread_id=11,
        )
        self.assertFalse(ok)
        self.assertEqual(status, "WRONG_THREAD")
        bot.send_message.assert_not_awaited()

        reply.message_thread_id = 11
        ok, status = await deliver_support_reply_to_user(
            bot,
            reply,
            store,
            expected_thread_id=22,
        )
        self.assertNotEqual(status, "WRONG_THREAD")
        self.assertTrue(ok)
