"""Сборка CompleteChassis. Сквозной цикл — отдельный срез."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import Command
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot_chassis.config import BotChassisConfig, SkuItem, resolved_origin
from bot_chassis.factory import create_complete_chassis
from bot_chassis.followup import PendingInputKind, PendingInputStore
from bot_chassis.middleware.error_monitor import ErrorAlertMiddleware
from bot_chassis.middleware.throttling import ThrottlingMiddleware
from bot_chassis.middleware.user_activity import UserActivityMiddleware
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import StorageEngine
from bot_chassis.storage.sqlite_support_thread_store import (
    SqliteSupportThreadStore,
    TicketLimitExceeded,
)
from bot_chassis.support_bridge import SupportThreadStore, send_user_report_to_support


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
        self.assertNotIn("buy_sku:donate_50", callbacks)
        self.assertIn("core_sup:cancel", callbacks)
        self.assertIn("core_sup:hub", callbacks)
        self.assertIn("Psybot", support_card.text)
        self.assertTrue(chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE))

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

    async def test_factory_returns_shared_pending_store_and_menu_hook(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
        )
        default_chassis = await create_complete_chassis(self.bot, config)
        self.assertIsInstance(default_chassis.pending_store, PendingInputStore)

        user = User(id=7, is_bot=False, first_name="N")
        await default_chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=1,
                    chat=Chat(id=7, type="private"),
                    from_user=user,
                    text="/support",
                ),
            ),
        )
        self.assertTrue(
            default_chassis.pending_store.is_active(7, PendingInputKind.SUPPORT_MESSAGE)
        )

        shared = PendingInputStore()
        events: list[tuple[int, bool]] = []

        async def before_menu(user_id: int) -> None:
            events.append((user_id, shared.is_active(user_id, PendingInputKind.SUPPORT_MESSAGE)))

        chassis = await create_complete_chassis(
            self.bot,
            config,
            pending_store=shared,
            before_chassis_menu_action=before_menu,
        )
        self.assertIs(chassis.pending_store, shared)

        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=2,
                message=Message(
                    message_id=2,
                    date=1,
                    chat=Chat(id=7, type="private"),
                    from_user=user,
                    text="/support",
                ),
            ),
        )
        self.assertEqual(events, [(7, False)])
        self.assertTrue(shared.is_active(7, PendingInputKind.SUPPORT_MESSAGE))

        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=3,
                message=Message(
                    message_id=3,
                    date=1,
                    chat=Chat(id=7, type="private"),
                    from_user=user,
                    text="/start",
                ),
            ),
        )
        self.assertFalse(shared.is_active(7, PendingInputKind.SUPPORT_MESSAGE))

        events.clear()
        for update_id, text in (
            (4, "👤 Личный кабинет"),
            (5, "ℹ️ Info"),
        ):
            await chassis.dp.feed_update(
                self.bot,
                Update(
                    update_id=update_id,
                    message=Message(
                        message_id=update_id,
                        date=1,
                        chat=Chat(id=7, type="private"),
                        from_user=user,
                        text=text,
                    ),
                ),
            )
        self.assertEqual([item[0] for item in events], [7, 7])

    async def test_factory_user_dossier_extra_ports(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            enable_payments=False,
        )

        async def extra_lines(user_id: int):
            return [f"hours:{user_id}"]

        def extra_rows(user_id: int):
            return [[("Grant hours", f"adm_ops:grant_hours:{user_id}")]]

        class Extra:
            def __init__(self) -> None:
                self.handle_callback = AsyncMock(return_value=True)

            def home_rows(self):
                return ()

        extra = Extra()
        chassis = await create_complete_chassis(
            self.bot,
            config,
            extra_admin_actions=extra,
            extra_user_dossier_lines=extra_lines,
            extra_user_dossier_rows=extra_rows,
        )
        await chassis.storage.users.upsert_user("bot_a", 16, username="ann")
        admin = User(id=100, is_bot=False, first_name="Root")
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=1,
                    chat=Chat(id=100, type="private"),
                    from_user=admin,
                    text="/user 16",
                ),
            ),
        )
        sent = next(
            item
            for item in self.session.requests
            if item.__class__.__name__ == "SendMessage" and "Досье пользователя" in item.text
        )
        self.assertTrue(sent.text.endswith("hours:16"))
        buttons = [
            (button.text, button.callback_data)
            for row in sent.reply_markup.inline_keyboard
            for button in row
        ]
        self.assertEqual(buttons[-2], ("Grant hours", "adm_ops:grant_hours:16"))
        self.assertEqual(buttons[-1], ("« Главное меню админки", "adm_home"))

        panel = Message(
            message_id=50,
            date=1,
            chat=Chat(id=100, type="private"),
            from_user=admin,
            text="dossier",
        )
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=2,
                callback_query=CallbackQuery(
                    id="c2",
                    from_user=admin,
                    chat_instance="x",
                    data="adm_ops:grant_hours:16",
                    message=panel,
                ),
            ),
        )
        extra.handle_callback.assert_awaited_once()

    async def test_ticket_limit_race_through_factory_storage(self) -> None:
        await create_storage(BotChassisConfig(bot_id="psybot", db_path=self.db_path))
        store_a = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
            max_active_tickets_per_user=1,
        )
        store_b = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="adhd",
            origin_telegram_bot_id=202,
            max_active_tickets_per_user=1,
        )
        self.assertTrue(store_a.can_send_ticket(7))
        self.assertTrue(store_b.can_send_ticket(7))

        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def worker(store: SqliteSupportThreadStore, header: int, copy: int, ticket_id: str) -> None:
            barrier.wait()
            try:
                store.register(-100, 7, header, copy, ticket_id=ticket_id)
                outcomes.append("ok")
            except TicketLimitExceeded:
                outcomes.append("limit")

        first = threading.Thread(target=worker, args=(store_a, 10, 11, "ticket-a"))
        second = threading.Thread(target=worker, args=(store_b, 20, 21, "ticket-b"))
        first.start()
        second.start()
        first.join()
        second.join()
        self.assertEqual(sorted(outcomes), ["limit", "ok"])

        store_a.can_send_ticket = lambda _user_id: True  # type: ignore[method-assign]
        store_b.can_send_ticket = lambda _user_id: True  # type: ignore[method-assign]

        class _Bot:
            def __init__(self, bot_id: int) -> None:
                self.id = bot_id
                self.sent: list[tuple[str, int]] = []
                self.deleted: list[tuple[int, int]] = []
                self._next_message_id = 100

            async def send_message(self, chat_id: int, text: str, **_kwargs):
                self.sent.append(("send", chat_id))
                message = SimpleNamespace(message_id=self._next_message_id)
                self._next_message_id += 1
                return message

            async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int):
                del from_chat_id, message_id
                self.sent.append(("copy", chat_id))
                message = SimpleNamespace(message_id=self._next_message_id)
                self._next_message_id += 1
                return message

            async def delete_message(self, chat_id: int, message_id: int) -> None:
                self.deleted.append((chat_id, message_id))

        bot_a = _Bot(101)
        bot_b = _Bot(202)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=8, username="ann", full_name="Ann"),
            chat=SimpleNamespace(id=8),
            message_id=50,
        )
        copied_a, copied_b = await asyncio.gather(
            send_user_report_to_support(bot_a, -100, user_message, store_a),
            send_user_report_to_support(bot_b, -100, user_message, store_b),
        )
        created = [item for item in (copied_a, copied_b) if item is not None]
        self.assertEqual(len(created), 1)
        self.assertTrue((copied_a is None) ^ (copied_b is None))
        loser = bot_a if copied_a is None else bot_b
        self.assertEqual(len(loser.deleted), 2)

        def inspect(conn):
            open_headers = conn.execute(
                """
                SELECT COUNT(*) FROM support_threads
                WHERE bot_id = 'psybot' AND user_id = 8
                  AND ticket_status = 'open' AND message_role = 'header'
                """
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT COUNT(*) FROM support_threads WHERE bot_id = 'psybot' AND user_id = 8"
            ).fetchone()[0]
            return open_headers, rows

        open_headers, rows = await StorageEngine(self.db_path).run(inspect)
        self.assertEqual(open_headers, 1)
        self.assertEqual(rows, 2)

    async def test_seven_bots_share_one_reply_through_factory(self) -> None:
        origin_session = _Session()
        origin_bot = Bot(token="100001:ABC", session=origin_session)
        config = BotChassisConfig(
            bot_id="psybot",
            origin_bot_id="bpd",
            db_path=self.db_path,
            support_chat_id=-100,
            enable_admin=False,
            enable_payments=False,
        )
        store = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=origin_bot.id,
        )
        chassis = await create_complete_chassis(
            origin_bot, config, thread_store=store
        )
        store.register(-100, 7, 10, 11, ticket_id="ticket-1")
        group = Chat(id=-100, type="supergroup")
        admin = User(id=14, is_bot=False, first_name="Admin")
        replied_to = Message(message_id=10, date=1, chat=group, text="ticket")
        reply = Message(
            message_id=12,
            date=1,
            chat=group,
            from_user=admin,
            text="answer",
            reply_to_message=replied_to,
        )
        bots = [origin_bot]
        sessions = [origin_session]
        for index in range(1, 7):
            session = _Session()
            bots.append(Bot(token=f"10000{index + 1}:ABC", session=session))
            sessions.append(session)
        for update_id, bot in enumerate(bots, 200):
            await chassis.dp.feed_update(bot, Update(update_id=update_id, message=reply))

        user_sends = [
            item
            for session in sessions
            for item in session.requests
            if item.__class__.__name__ in {"SendMessage", "CopyMessage"}
            and getattr(item, "chat_id", None) == 7
        ]
        self.assertEqual(len(user_sends), 2)
        self.assertEqual(store.resolve_ticket(-100, 10).ticket_status, "answered")
        origin_session.requests.clear()
        await chassis.dp.feed_update(origin_bot, Update(update_id=300, message=reply))
        self.assertFalse(
            any(
                item.__class__.__name__ in {"SendMessage", "CopyMessage"}
                and getattr(item, "chat_id", None) == 7
                for item in origin_session.requests
            )
        )
        for extra in bots[1:]:
            await extra.session.close()
        await origin_bot.session.close()


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
