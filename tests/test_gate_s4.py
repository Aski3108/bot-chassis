"""Gate S4-A и S4-B: старт процесса и закрытие истории поддержки."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteMessage, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, Message, Update, User

from bot_chassis.config import BotChassisConfig
from bot_chassis.contracts import CB_NAV_CLOSE
from bot_chassis.factory import create_complete_chassis
from bot_chassis.lifecycle import UserScreenTracker
from bot_chassis.router import create_button_chassis_router
from bot_chassis.service_notify import deliver_startup_notification
from bot_chassis.storage.sqlite_support_thread_store import SupportTicketMessage
from bot_chassis.support_bridge import send_support_history, support_history_text


class TestStartupNotification(unittest.IsolatedAsyncioTestCase):
    async def test_startup_notification_uses_audit_thread(self) -> None:
        bot = AsyncMock()
        config = BotChassisConfig(
            bot_id='proj<script>&"',
            audit_chat_id=-200,
            audit_thread_id=22,
            support_chat_id=-100,
            superadmin_ids=(11, 22),
        )
        self.assertFalse(await deliver_startup_notification(None, config))
        bot.send_message.assert_not_awaited()

        sent = await deliver_startup_notification(bot, config)
        self.assertTrue(sent)
        bot.send_message.assert_awaited_once_with(
            -200,
            "🟢 <b>Bot Chassis запущен</b>\nПроект: <b>proj&lt;script&gt;&amp;&quot;</b>",
            parse_mode="HTML",
            message_thread_id=22,
        )

    async def test_startup_notification_falls_back_to_first_superadmin_only(self) -> None:
        bot = AsyncMock()
        config = BotChassisConfig(
            bot_id="bot_a",
            support_chat_id=-100,
            superadmin_ids=(11, 22),
        )
        self.assertTrue(await deliver_startup_notification(bot, config))
        bot.send_message.assert_awaited_once_with(
            11,
            "🟢 <b>Bot Chassis запущен</b>\nПроект: <b>bot_a</b>",
            parse_mode="HTML",
        )
        self.assertNotIn("message_thread_id", bot.send_message.await_args.kwargs)

        bot.send_message.reset_mock()
        bot.send_message.side_effect = TelegramBadRequest(method=SendMessage(chat_id=11, text="x"), message="boom")
        self.assertFalse(await deliver_startup_notification(bot, config))
        bot.send_message.assert_awaited_once()

    async def test_startup_notification_does_not_use_support_chat(self) -> None:
        bot = AsyncMock()
        config = BotChassisConfig(bot_id="bot_a", support_chat_id=-100, support_thread_id=7)
        self.assertFalse(await deliver_startup_notification(bot, config))
        bot.send_message.assert_not_awaited()

        empty = BotChassisConfig(bot_id="bot_a")
        self.assertFalse(await deliver_startup_notification(bot, empty))
        bot.send_message.assert_not_awaited()


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        if method.__class__.__name__ == "SendMessage":
            return Message(
                message_id=len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestStartupHook(unittest.IsolatedAsyncioTestCase):
    async def test_factory_registers_startup_notification_hook(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        try:
            config = BotChassisConfig(
                bot_id="bot_a",
                db_path=os.path.join(tmp.name, "chassis.db"),
                audit_chat_id=-200,
                audit_thread_id=22,
                support_chat_id=-100,
                superadmin_ids=(11, 22),
                enable_admin=False,
                enable_payments=False,
                enable_buttons=False,
            )
            chassis = await create_complete_chassis(bot, config)
            registered = len(chassis.dp.startup.handlers)
            await chassis.dp.emit_startup(bot=bot)
            await chassis.dp.emit_startup(bot=bot)
            self.assertEqual(len(chassis.dp.startup.handlers), registered)
            startup = [
                item
                for item in session.requests
                if item.__class__.__name__ == "SendMessage" and "Bot Chassis запущен" in (getattr(item, "text", "") or "")
            ]
            self.assertEqual(len(startup), 2)
            self.assertTrue(all(item.chat_id == -200 and item.message_thread_id == 22 for item in startup))
            self.assertTrue(all(item.chat_id != -100 and item.chat_id not in (11, 22) for item in startup))
        finally:
            await bot.session.close()
            tmp.cleanup()


def _history_store() -> SimpleNamespace:
    message = SupportTicketMessage(
        direction="user_to_support",
        telegram_chat_id=-1001234567890,
        telegram_message_id=42,
        message_thread_id=7,
        created_at="2026-01-02 03:04:05",
    )
    ticket = SimpleNamespace(support_chat_id=-100555, message_thread_id=3)
    return SimpleNamespace(
        ticket=ticket,
        messages=(message,),
        get_ticket=lambda ticket_id: ticket,
        header_message_id=lambda ticket_id: 10,
        list_messages=lambda ticket_id, support_chat_id: (message,),
    )


class _CloseSession(BaseSession):
    def __init__(self, delete_error: Exception | None = None, edit_error: Exception | None = None) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.delete_error = delete_error
        self.edit_error = edit_error

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        name = method.__class__.__name__
        if name == "DeleteMessage" and self.delete_error is not None:
            raise self.delete_error
        if name == "EditMessageReplyMarkup" and self.edit_error is not None:
            raise self.edit_error
        self.requests.append(method)
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestSupportHistoryClose(unittest.IsolatedAsyncioTestCase):
    async def test_support_history_has_plain_close_button(self) -> None:
        store = _history_store()
        bot = AsyncMock()
        self.assertTrue(await send_support_history(bot, store, "hist-1"))
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["text"], support_history_text("hist-1", store.messages))
        self.assertEqual(kwargs["reply_to_message_id"], 10)
        self.assertEqual(kwargs["message_thread_id"], 3)
        rows = kwargs["reply_markup"].inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 1)
        self.assertEqual(rows[0][0].text, "Закрыть")
        self.assertEqual(rows[0][0].callback_data, CB_NAV_CLOSE)

    async def test_history_close_forgets_tracker_before_api(self) -> None:
        screens = UserScreenTracker()
        screens.remember_card(7, 7, 12)
        session = _CloseSession()
        seen: dict[str, object] = {}

        async def make_request(bot: Bot, method: TelegramMethod, timeout: int | None = None):
            if method.__class__.__name__ == "DeleteMessage":
                seen["card"] = screens.get_card(7)
            return await _CloseSession.make_request(session, bot, method, timeout)

        session.make_request = make_request  # type: ignore[method-assign]
        await _press_close(session, screens, "core_nav:close", message_id=12)
        self.assertIsNone(seen["card"])
        self.assertIsNone(screens.get_card(7))
        names = [item.__class__.__name__ for item in session.requests]
        self.assertEqual(names.count("DeleteMessage"), 1)
        self.assertNotIn("EditMessageReplyMarkup", names)
        self.assertEqual(names.count("AnswerCallbackQuery"), 1)

    async def test_history_close_bad_request_drops_markup(self) -> None:
        await self._assert_delete_fallback(
            TelegramBadRequest(method=DeleteMessage(chat_id=7, message_id=12), message="not found")
        )

    async def test_history_close_forbidden_drops_markup(self) -> None:
        await self._assert_delete_fallback(
            TelegramForbiddenError(method=DeleteMessage(chat_id=7, message_id=12), message="blocked")
        )

    async def test_history_close_inaccessible_answers_once(self) -> None:
        screens = UserScreenTracker()
        screens.remember_card(7, 7, 12)
        session = _CloseSession(
            edit_error=TelegramBadRequest(
                method=DeleteMessage(chat_id=7, message_id=12),
                message="fallback failed",
            )
        )
        await _press_close(
            session,
            screens,
            "core_nav:close",
            message=InaccessibleMessage(chat=Chat(id=7, type="private"), message_id=12, date=0),
        )
        names = [item.__class__.__name__ for item in session.requests]
        self.assertEqual(names, ["AnswerCallbackQuery"])
        self.assertIsNone(screens.get_card(7))

        broken = _CloseSession(
            delete_error=TelegramBadRequest(
                method=DeleteMessage(chat_id=7, message_id=12),
                message="not found",
            ),
            edit_error=RuntimeError("markup edit failed"),
        )
        await _press_close(broken, UserScreenTracker(), "core_nav:close")

    async def _assert_delete_fallback(self, error: Exception) -> None:
        session = _CloseSession(delete_error=error)
        await _press_close(session, UserScreenTracker(), "core_nav:close")
        edits = [item for item in session.requests if item.__class__.__name__ == "EditMessageReplyMarkup"]
        self.assertEqual(len(edits), 1)
        self.assertIsNone(edits[0].reply_markup)
        self.assertNotIn("DeleteMessage", [item.__class__.__name__ for item in session.requests])


async def _press_close(
    session: _CloseSession,
    screens: UserScreenTracker,
    data: str,
    message_id: int = 12,
    message: Message | InaccessibleMessage | None = None,
) -> None:
    bot = Bot(token="123456:ABC", session=session)
    try:
        router = create_button_chassis_router(screen_tracker=screens, enable_support=False)
        dp = Dispatcher()
        dp.include_router(router)
        user = User(id=7, is_bot=False, first_name="Ann")
        if message is None:
            message = Message(
                message_id=message_id,
                date=1,
                chat=Chat(id=7, type="private"),
                from_user=user,
                text="history",
            )
        await dp.feed_update(
            bot,
            Update(
                update_id=1,
                callback_query=CallbackQuery(
                    id="cb-1",
                    from_user=user,
                    chat_instance="x",
                    data=data,
                    message=message,
                ),
            ),
        )
    finally:
        await bot.session.close()
