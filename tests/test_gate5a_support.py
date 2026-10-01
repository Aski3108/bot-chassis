"""Gate 5A: обзор поддержки, скрытая /support, внешний каталог донатов, раздельные pending."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot_chassis.admin.lookup import admin_lookup_is_waiting, reset_admin_lookups
from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.admin.router import CB_FIND
from bot_chassis.contracts import BTN_SUPPORT_RU
from bot_chassis.factory import create_complete_chassis
from bot_chassis.followup import PendingInput, PendingInputKind, PendingScope
from bot_chassis.localization import ChassisScreen


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
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="N")


class TestSupportScreens(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "support.db")
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        reset_admin_lookups()

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()
        reset_admin_lookups()

    def _texts(self) -> list[str]:
        return [
            item.text
            for item in self.session.requests
            if item.__class__.__name__ in {"SendMessage", "EditMessageText"}
        ]

    def _callbacks(self, text_part: str) -> list[str]:
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

    async def _message(self, chassis, user_id: int, text: str, update_id: int) -> None:
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=1,
                    chat=Chat(id=user_id, type="private"),
                    from_user=_user(user_id),
                    text=text,
                ),
            ),
        )

    async def _callback(self, chassis, user_id: int, data: str, update_id: int, panel_text: str = "card") -> None:
        panel = Message(
            message_id=40,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=_user(user_id),
            text=panel_text,
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

    async def test_overview_request_donate_back_and_hidden_review(self) -> None:
        started: list[int] = []

        async def render_start(context) -> ChassisScreen:
            started.append(context.user_id)
            return ChassisScreen(text="стартовый экран", markup=None)

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(14,),
            enable_admin=True,
            enable_payments=True,
            skus=(
                SkuItem("donate_50", "50", "d", 50, False),
                SkuItem("donate_100", "100", "d", 100, False),
                SkuItem("donate_500", "500", "d", 500, False),
                SkuItem("vip", "VIP", "paid", 150, True),
            ),
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            render_start_callback=render_start,
            donation_hint="ориентир ~70 ₽ за 50 ⭐",
        )
        await self._message(chassis, 7, BTN_SUPPORT_RU, 1)
        self.assertFalse(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))
        overview = "\n".join(self._texts())
        self.assertIn("Выберите действие", overview)
        callbacks = self._callbacks("Выберите действие")
        self.assertIn("core_sup:request", callbacks)
        self.assertIn("core_sup:donate", callbacks)
        self.assertIn("core_sup:back", callbacks)
        self.assertNotIn("core_sup:review", callbacks)
        self.assertNotIn("buy_sku:donate_50", callbacks)

        await self._callback(chassis, 7, "core_sup:request", 2)
        self.assertTrue(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))
        request_cb = self._callbacks("Можно отправить текст")
        self.assertIn("core_sup:cancel", request_cb)
        self.assertNotIn("core_sup:hub", request_cb)
        self.assertNotIn("buy_sku:donate_50", request_cb)

        await self._callback(chassis, 7, "core_sup:hub", 3)
        self.assertFalse(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))

        await self._callback(chassis, 7, "core_sup:donate", 4)
        donate_cb = self._callbacks("Поддержать проект")
        self.assertEqual(
            donate_cb,
            ["buy_sku:donate_50", "buy_sku:donate_100", "buy_sku:donate_500", "core_sup:hub"],
        )
        self.assertTrue(any("ориентир ~70" in text for text in self._texts()))
        self.assertNotIn("buy_sku:vip", donate_cb)

        self.session.requests.clear()
        await self._callback(chassis, 7, "core_sup:back", 5)
        self.assertEqual(started, [7])
        self.assertTrue(any("стартовый экран" in text for text in self._texts()))

    async def test_hidden_support_command_and_empty_catalog(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            skus=(SkuItem("vip", "VIP", "paid", 150, True),),
        )
        chassis = await create_complete_chassis(self.bot, config, donation_catalog=())
        await self._message(chassis, 7, "/support", 1)
        self.assertTrue(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))
        self.assertTrue(any("Можно отправить текст" in text for text in self._texts()))

        self.session.requests.clear()
        chassis.pending_store.clear(7)
        await self._message(chassis, 7, BTN_SUPPORT_RU, 2)
        self.assertFalse(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))
        self.assertNotIn("core_sup:donate", self._callbacks("Выберите действие"))

    async def test_external_catalog_and_parallel_admin_lookup(self) -> None:
        catalog = (
            SkuItem("d50", "50 Stars", "d", 50, False),
            SkuItem("d100", "100 Stars", "d", 100, False),
            SkuItem("d500", "500 Stars", "d", 500, False),
        )
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(14,),
            enable_admin=True,
            skus=(SkuItem("donate_1", "ignored", "d", 1, False),),
        )
        chassis = await create_complete_chassis(self.bot, config, donation_catalog=catalog)
        await chassis.storage.users.upsert_user("bot_a", 16, username="neo")

        panel = Message(message_id=50, date=1, chat=Chat(id=14, type="private"), text="admin")
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=1,
                callback_query=CallbackQuery(
                    id="1",
                    from_user=_user(14),
                    chat_instance="x",
                    data=CB_FIND,
                    message=panel,
                ),
            ),
        )
        self.assertTrue(
            chassis.pending_store.is_active(14, PendingInputKind.ADMIN_LOOKUP, scope=PendingScope.ADMIN)
        )
        self.assertFalse(admin_lookup_is_waiting("bot_a", 14))

        await self._message(chassis, 14, "/support", 2)
        self.assertTrue(chassis.pending_store.is_active(14, PendingInputKind.SUPPORT_MESSAGE))
        self.assertTrue(
            chassis.pending_store.is_active(14, PendingInputKind.ADMIN_LOOKUP, scope=PendingScope.ADMIN)
        )

        await self._message(chassis, 7, BTN_SUPPORT_RU, 3)
        await self._callback(chassis, 7, "core_sup:donate", 4)
        donate_cb = self._callbacks("Поддержать проект")
        self.assertEqual(
            donate_cb[:3],
            ["buy_sku:d50", "buy_sku:d100", "buy_sku:d500"],
        )
        self.assertNotIn("buy_sku:donate_1", donate_cb)

        self.session.requests.clear()
        await self._callback(chassis, 7, "buy_sku:d50", 5)
        invoices = [
            request
            for request in self.session.requests
            if request.__class__.__name__ == "SendInvoice"
        ]
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].prices[0].amount, 50)

    async def test_successful_ticket_closes_prompt_card(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            support_chat_id=-1003299,
        )
        chassis = await create_complete_chassis(self.bot, config)
        await self._message(chassis, 7, "/support", 1)
        self.assertTrue(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))
        self.session.requests.clear()
        await self._message(chassis, 7, "нужна помощь", 2)
        self.assertFalse(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))
        deletes = [
            item
            for item in self.session.requests
            if item.__class__.__name__ == "DeleteMessage"
        ]
        self.assertTrue(deletes)
        self.assertTrue(any("передано в службу поддержки" in text for text in self._texts()))

    def test_pending_input_keeps_old_positional_created_at(self) -> None:
        stamp = 123.5
        pending = PendingInput(PendingInputKind.SUPPORT_MESSAGE, None, None, None, stamp)
        self.assertEqual(pending.created_at, stamp)
        self.assertIsNone(pending.ticket_id)
