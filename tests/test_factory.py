"""Сборка CompleteChassis. Сквозной цикл — отдельный срез."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import Command
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from bot_chassis.config import BotChassisConfig, SkuItem, resolved_origin
from bot_chassis.factory import create_complete_chassis
from bot_chassis.middleware.error_monitor import ErrorAlertMiddleware
from bot_chassis.middleware.throttling import ThrottlingMiddleware
from bot_chassis.middleware.user_activity import UserActivityMiddleware
from bot_chassis.storage import create_storage
from bot_chassis.storage.sqlite_support_thread_store import SqliteSupportThreadStore
from bot_chassis.support_bridge import SupportThreadStore


class TestConfigCompatibility(unittest.TestCase):
    def test_new_fields_preserve_defaults_and_positional_arguments(self) -> None:
        config = BotChassisConfig("bot_a", True)
        sku = SkuItem("sku", "Title", "Description", 10)

        self.assertTrue(config.enable_buttons)
        self.assertIsNone(config.origin_bot_id)
        self.assertTrue(sku.issues_voucher)

    def test_resolved_origin_prefers_explicit_origin(self) -> None:
        self.assertEqual(resolved_origin(BotChassisConfig("bot_a")), "bot_a")
        self.assertEqual(
            resolved_origin(BotChassisConfig("tenant", origin_bot_id="origin")),
            "origin",
        )


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
                message_id=50,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestCompleteChassis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def test_factory_wires_ports_middleware_and_router_order(self) -> None:
        domain = Router(name="domain")

        @domain.message(Command("ping"))
        async def handle_ping(message: Message) -> None:
            await message.answer("pong")

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            enable_referrals=False,
            enable_payments=True,
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            domain_router=domain,
            domain_rows=(("Чаты",),),
        )
        names = [router.name for router in chassis.dp.sub_routers]
        self.assertEqual(
            names,
            ["admin", "payments", "localization_router", "domain", "chassis_start", "button_chassis"],
        )
        ours = [item for item in chassis.dp.update.outer_middleware if item.__class__.__module__.startswith("bot_chassis.")]
        self.assertIsInstance(ours[0], ErrorAlertMiddleware)
        self.assertIsInstance(ours[1], ThrottlingMiddleware)
        self.assertIsInstance(ours[2], UserActivityMiddleware)
        self.assertTrue(await chassis.storage.roles.has_any_role("bot_a", 100, ("superadmin",)))
        self.assertIs(chassis.locale_cache, ours[2]._locale_cache)
        self.assertIsInstance(chassis.thread_store, SupportThreadStore)

        await chassis.storage.users.upsert_user("bot_a", 7, username="ann")
        slots = await chassis.cabinet.get_cabinet_slots("bot_a", 7)
        slot_ids = [slot.slot_id for slot in slots]
        self.assertIn("vouchers", slot_ids)
        self.assertNotIn("referrals", slot_ids)
        allowed, _reason = await chassis.work_gate.can_accept_work("bot_a", 7)
        self.assertTrue(allowed)

        user = User(id=7, is_bot=False, first_name="N")
        message = Message(
            message_id=1,
            date=1,
            chat=Chat(id=7, type="private"),
            from_user=user,
            text="/start ref_100",
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=message))
        sent = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage" and item.chat_id == 7]
        self.assertTrue(any("Главное меню" in item.text for item in sent))
        self.assertIsNotNone(sent[-1].reply_markup)

        self.session.requests.clear()
        ping = Message(
            message_id=2,
            date=1,
            chat=Chat(id=7, type="private"),
            from_user=user,
            text="/ping",
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=2, message=ping))
        self.assertTrue(any(item.text == "pong" for item in self.session.requests if item.__class__.__name__ == "SendMessage"))

    async def test_factory_reuses_storage_and_custom_cabinet(self) -> None:
        config = BotChassisConfig(bot_id="bot_a", db_path=self.db_path, enable_admin=False, enable_payments=False)
        storage = await create_storage(config)

        class Cabinet:
            async def get_cabinet_slots(self, bot_id: str, user_id: int):
                return []

        cabinet = Cabinet()
        given_dp = Dispatcher()
        chassis = await create_complete_chassis(
            self.bot,
            config,
            dp=given_dp,
            storage=storage,
            cabinet_provider=cabinet,
        )
        self.assertIs(chassis.storage, storage)
        self.assertIs(chassis.dp, given_dp)
        self.assertIs(chassis.cabinet, cabinet)
        names = [router.name for router in chassis.dp.sub_routers]
        self.assertNotIn("admin", names)
        self.assertNotIn("payments", names)
        self.assertIn("button_chassis", names)

    async def test_custom_vouchers_and_welcome_text(self) -> None:
        class Vouchers:
            async def get_active_vouchers(self, bot_id: str, user_id: int, sku_code: str | None = None):
                return []

            async def redeem_voucher(self, bot_id: str, user_id: int, voucher_id: str):
                return True, None

        vouchers = Vouchers()
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            welcome_text="<b>Привет!</b>",
            enable_admin=False,
            enable_payments=False,
        )
        chassis = await create_complete_chassis(self.bot, config, vouchers_provider=vouchers)
        self.assertIs(chassis.vouchers, vouchers)

        user = User(id=7, is_bot=False, first_name="N")
        message = Message(
            message_id=1,
            date=1,
            chat=Chat(id=7, type="private"),
            from_user=user,
            text="/start",
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=message))
        sent = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertTrue(any(item.text == "<b>Привет!</b>" for item in sent))

    async def test_factory_keeps_json_default_and_accepts_explicit_sqlite_store(self) -> None:
        config = BotChassisConfig(
            bot_id="tenant",
            origin_bot_id="bpd",
            db_path=self.db_path,
            support_chat_id=-100,
            enable_admin=False,
            enable_payments=False,
        )
        default_chassis = await create_complete_chassis(self.bot, config)
        self.assertIsInstance(default_chassis.thread_store, SupportThreadStore)

        explicit_store = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="tenant",
            origin_bot_id="bpd",
            origin_telegram_bot_id=self.bot.id,
        )
        explicit_chassis = await create_complete_chassis(
            self.bot,
            config,
            thread_store=explicit_store,
        )
        self.assertIs(explicit_chassis.thread_store, explicit_store)

        explicit_store.register(-100, 7, 10, 11, ticket_id="ticket-1")
        foreign_session = _Session()
        foreign_bot = Bot(token="654321:ABC", session=foreign_session)
        group = Chat(id=-100, type="supergroup")
        admin = User(id=14, is_bot=False, first_name="Admin")
        replied_to = Message(
            message_id=10,
            date=1,
            chat=group,
            text="ticket",
        )
        reply = Message(
            message_id=12,
            date=1,
            chat=group,
            from_user=admin,
            text="answer",
            reply_to_message=replied_to,
        )
        await explicit_chassis.dp.feed_update(
            foreign_bot,
            Update(update_id=100, message=reply),
        )
        self.assertFalse(
            any(item.__class__.__name__ == "SendMessage" for item in foreign_session.requests)
        )
        await foreign_bot.session.close()

    async def test_factory_support_extras_and_commands_are_private(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            skus=(SkuItem("donate_50", "Поддержать", "Донат", 50, False),),
        )
        info_renderer = AsyncMock(return_value=None)
        chassis = await create_complete_chassis(
            self.bot,
            config,
            project_label="Psybot",
            render_info_callback=info_renderer,
        )
        user = User(id=7, is_bot=False, first_name="N")
        support = Message(
            message_id=1,
            date=1,
            chat=Chat(id=7, type="private"),
            from_user=user,
            text="/support",
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=support))
        support_card = next(
            item
            for item in self.session.requests
            if item.__class__.__name__ == "SendMessage" and "Служба поддержки" in item.text
        )
        callbacks = [
            button.callback_data
            for row in support_card.reply_markup.inline_keyboard
            for button in row
        ]
        self.assertIn("buy_sku:donate_50", callbacks)
        self.assertIn("Psybot", support_card.text)

        self.session.requests.clear()
        for update_id, command in enumerate(("/start", "/menu", "/help", "/support"), 10):
            group_message = Message(
                message_id=update_id,
                date=1,
                chat=Chat(id=-100, type="supergroup"),
                from_user=user,
                text=command,
            )
            await chassis.dp.feed_update(
                self.bot,
                Update(update_id=update_id, message=group_message),
            )
        self.assertFalse(
            any(
                item.__class__.__name__ == "SendMessage" and item.chat_id == -100
                for item in self.session.requests
            )
        )


def _load_runner():
    path = os.path.join(os.path.dirname(__file__), "..", "examples", "run_complete_chassis.py")
    spec = importlib.util.spec_from_file_location("run_complete_chassis", os.path.abspath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCompleteRunner(unittest.IsolatedAsyncioTestCase):
    async def test_config_from_env_and_missing_token_does_not_poll(self) -> None:
        runner = _load_runner()
        config = runner.build_config(
            {
                "CHASSIS_BOT_ID": "shop",
                "ADMIN_IDS": "10, bad, 11",
                "SUPPORT_CHAT_ID": "-100",
                "CHASSIS_ENABLE_REFERRALS": "yes",
            }
        )
        self.assertEqual(config.bot_id, "shop")
        self.assertEqual(config.superadmin_ids, (10, 11))
        self.assertEqual(config.support_chat_id, -100)
        self.assertTrue(config.enable_referrals)
        self.assertEqual(config.skus[0].stars_price, 1)
        self.assertEqual(config.skus[0].sku_code, "demo")

        with patch.dict(os.environ, {"BOT_TOKEN": "  "}, clear=False):
            await runner.main()


if __name__ == "__main__":
    unittest.main()
