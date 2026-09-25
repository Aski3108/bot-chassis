"""Cross-cutting invariants required before mounting a multi-bot product."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from bot_chassis.admin.router import REFUND_OTHER_BOT, create_admin_router
from bot_chassis.config import BotChassisConfig, SkuItem, resolved_alert_chat_id
from bot_chassis.factory import create_complete_chassis
from bot_chassis.storage import create_storage
from bot_chassis.storage.sqlite_support_thread_store import SqliteSupportThreadStore
from bot_chassis.support_bridge import SupportThreadStore, deliver_support_reply_to_user


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod,
        timeout: int | None = None,
    ):
        self.requests.append(method)
        if method.__class__.__name__ == "SendMessage":
            return Message(
                message_id=50,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
    ):
        yield b""


class TestMountInvariants(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.config = BotChassisConfig(
            bot_id="tenant_x",
            origin_bot_id="origin_a",
            db_path=self.db_path,
            superadmin_ids=(900,),
            support_chat_id=-100,
            audit_chat_id=-101,
            skus=(
                SkuItem("voucher", "Voucher", "One task", 50),
                SkuItem("donate_50", "Donate", "No voucher", 50, False),
            ),
        )
        self.storage = await create_storage(self.config)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_network_mount_contract(self) -> None:
        self.assertEqual(
            tuple(BotChassisConfig.__dataclass_fields__)[-1],
            "origin_bot_id",
        )
        self.assertEqual(tuple(SkuItem.__dataclass_fields__)[-1], "issues_voucher")
        self.assertEqual(resolved_alert_chat_id(self.config), self.config.audit_chat_id)
        self.assertEqual(
            resolved_alert_chat_id(BotChassisConfig("tenant_x", support_chat_id=-200)),
            -200,
        )

        await self.storage.users.upsert_user("tenant_x", 7)
        first, first_created = await self.storage.transactions.record_successful_payment(
            bot_id="tenant_x",
            user_id=7,
            telegram_payment_charge_id="charge-101",
            payment_id="shared-payment",
            sku_code="voucher",
            amount=50,
            merchant_origin_bot_id="origin_a",
            merchant_telegram_bot_id=101,
        )
        second, second_created = await self.storage.transactions.record_successful_payment(
            bot_id="tenant_x",
            user_id=7,
            telegram_payment_charge_id="charge-202",
            payment_id="shared-payment",
            sku_code="donate_50",
            amount=50,
            merchant_origin_bot_id="origin_b",
            merchant_telegram_bot_id=202,
            voucher_status="redeemed",
        )
        self.assertTrue(first_created)
        self.assertTrue(second_created)
        self.assertNotEqual(first.voucher_id, second.voucher_id)
        active = await self.storage.transactions.get_active_vouchers("tenant_x", 7)
        self.assertEqual([item.sku_code for item in active], ["voucher"])

        await self.storage.transactions.record_successful_payment(
            bot_id="tenant_x",
            user_id=7,
            telegram_payment_charge_id="charge-foreign",
            payment_id="foreign-payment",
            sku_code="voucher",
            amount=50,
            merchant_origin_bot_id="origin_a",
            merchant_telegram_bot_id=101,
        )

        refund_session = _Session()
        refund_bot = Bot(token="202:ABC", session=refund_session)
        refund_dp = Dispatcher()
        refund_dp.include_router(
            create_admin_router("tenant_x", self.storage, self.config)
        )
        command = Message(
            message_id=1,
            date=1,
            chat=Chat(id=900, type="private"),
            from_user=User(id=900, is_bot=False, first_name="Root"),
            text="/refund 7 foreign-payment",
        )
        await refund_dp.feed_update(refund_bot, Update(update_id=1, message=command))
        self.assertFalse(
            any(
                request.__class__.__name__ == "RefundStarPayment"
                for request in refund_session.requests
            )
        )
        self.assertTrue(
            any(
                request.__class__.__name__ == "SendMessage"
                and request.text == REFUND_OTHER_BOT
                for request in refund_session.requests
            )
        )
        await refund_bot.session.close()

        factory_session = _Session()
        factory_bot = Bot(token="101:ABC", session=factory_session)
        default_chassis = await create_complete_chassis(
            factory_bot,
            BotChassisConfig(
                bot_id="tenant_x",
                origin_bot_id="origin_a",
                db_path=self.db_path,
                enable_admin=False,
                enable_payments=False,
            ),
        )
        self.assertIsInstance(default_chassis.thread_store, SupportThreadStore)
        sqlite_store = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="tenant_x",
            origin_bot_id="origin_a",
            origin_telegram_bot_id=101,
        )
        explicit_chassis = await create_complete_chassis(
            factory_bot,
            BotChassisConfig(
                bot_id="tenant_x",
                origin_bot_id="origin_a",
                db_path=self.db_path,
                enable_admin=False,
                enable_payments=False,
            ),
            thread_store=sqlite_store,
        )
        self.assertIs(explicit_chassis.thread_store, sqlite_store)

        sqlite_store.register(-100, 7, 10, 11, ticket_id="ticket-1")
        sqlite_store.register(-100, 7, 20, 21, ticket_id="ticket-2")
        reply = Message(
            message_id=30,
            date=1,
            chat=Chat(id=-100, type="supergroup"),
            from_user=User(id=900, is_bot=False, first_name="Root"),
            text="answer",
            reply_to_message=Message(
                message_id=11,
                date=1,
                chat=Chat(id=-100, type="supergroup"),
                text="ticket",
            ),
        )
        delivered, _status = await deliver_support_reply_to_user(
            factory_bot,
            reply,
            sqlite_store,
        )
        self.assertTrue(delivered)
        self.assertIsNone(sqlite_store.resolve_ticket(-100, 10))
        self.assertEqual(
            sqlite_store.resolve_ticket(-100, 20).ticket_id,
            "ticket-2",
        )
        await factory_bot.session.close()
