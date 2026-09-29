"""Gate 12: миграция 0.2.2→0.3.0, контракт кузова, одиночный бот и сеть из семи."""

from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberBanned,
    ChatMemberMember,
    ChatMemberUpdated,
    Message,
    Update,
    User,
)
from loguru import logger

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.contracts import BTN_INFO_RU, BTN_SUPPORT_RU
from bot_chassis.factory import create_complete_chassis
from bot_chassis.localization import ChassisScreen
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import SCHEMA_VERSION, StorageEngine
from bot_chassis.user_lifecycle import CANON_ALLOWED_UPDATES, warn_if_my_chat_member_missing

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_022 = ROOT / "tests" / "fixtures" / "schema_0_2_2.sql"
ORIGINS = tuple(f"bot-{index}" for index in range(1, 8))
NEW_NONE_KWONLY = (
    "render_start_callback",
    "on_locale_changed",
    "initial_locale_policy",
    "initial_locale_resolver",
    "bot_display_name_provider",
    "allowed_updates",
    "donation_catalog",
    "donation_hint",
    "review_sink",
    "backup_policy",
    "reporting_policy",
    "process_control",
)


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name in {"SendMessage", "EditMessageText"}:
            markup = getattr(method, "reply_markup", None)
            if markup is not None and markup.__class__.__name__ != "InlineKeyboardMarkup":
                markup = None
            return Message(
                message_id=getattr(method, "message_id", None) or len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0) or 7, type="private"),
                text=getattr(method, "text", ""),
                reply_markup=markup,
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _user(user_id: int, language_code: str = "ru") -> User:
    return User(id=user_id, is_bot=False, first_name="N", language_code=language_code)


def _private(user_id: int, text: str, message_id: int = 1) -> Message:
    return Message(
        message_id=message_id,
        date=1,
        chat=Chat(id=user_id, type="private"),
        from_user=_user(user_id),
        text=text,
    )


def _texts(session: _Session):
    return [
        item
        for item in session.requests
        if item.__class__.__name__ in {"SendMessage", "EditMessageText"}
    ]


class TestGate12FactoryContract(unittest.TestCase):
    def test_new_factory_params_are_keyword_only_none(self) -> None:
        signature = inspect.signature(create_complete_chassis)
        for name in NEW_NONE_KWONLY:
            param = signature.parameters[name]
            self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY, name)
            self.assertIsNone(param.default, name)

    def test_canon_updates_include_membership(self) -> None:
        self.assertEqual(
            CANON_ALLOWED_UPDATES,
            ("message", "callback_query", "pre_checkout_query", "my_chat_member"),
        )


class TestGate12Migration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "from022.db")

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_copy_of_0_2_2_migrates_twice_without_losing_rows(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA_022.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO users (bot_id, user_id, username, language_code) VALUES ('tenant', 7, 'ann', 'ru')"
            )
            conn.execute(
                """
                INSERT INTO transactions (
                    bot_id, user_id, provider, payment_id, telegram_payment_charge_id,
                    merchant_origin_bot_id, merchant_telegram_bot_id, sku_code, amount,
                    currency, status, voucher_id, voucher_status
                ) VALUES (
                    'tenant', 7, 'telegram_stars', 'chg-old', 'chg-old',
                    'bot-1', 101, 'vip', 150, 'XTR', 'paid', 'v-old', 'issued'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO support_threads (
                    bot_id, support_chat_id, support_message_id, user_id,
                    origin_bot_id, ticket_id, message_role, ticket_status
                ) VALUES ('tenant', -100, 10, 7, 'bot-1', 't-1', 'header', 'answered')
                """
            )
            conn.commit()
        finally:
            conn.close()

        engine = StorageEngine(self.db_path)
        await engine.initialize()
        await engine.initialize()
        self.assertEqual(SCHEMA_VERSION, "0.3")

        def inspect_db(connection):
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            user_cols = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            support_cols = {row[1] for row in connection.execute("PRAGMA table_info(support_threads)")}
            review_cols = {row[1] for row in connection.execute("PRAGMA table_info(review_submissions)")}
            status = connection.execute(
                "SELECT ticket_status FROM support_threads WHERE ticket_id = 't-1'"
            ).fetchone()[0]
            users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            txs = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            return tables, user_cols, support_cols, review_cols, status, users, txs

        tables, user_cols, support_cols, review_cols, status, users, txs = await engine.run(inspect_db)
        for name in (
            "user_bot_statuses",
            "support_ticket_messages",
            "review_submissions",
            "scheduled_job_runs",
            "chassis_events",
        ):
            self.assertIn(name, tables, name)
        self.assertIn("telegram_language_code", user_cols)
        self.assertIn("locale_source", user_cols)
        self.assertIn("message_thread_id", support_cols)
        self.assertIn("moderation_claim_token", review_cols)
        self.assertEqual(status, "closed")
        self.assertEqual(users, 1)
        self.assertEqual(txs, 1)

        storage = await create_storage(BotChassisConfig(bot_id="tenant", db_path=self.db_path))
        user = await storage.users.get_user("tenant", 7)
        self.assertEqual(user.username, "ann")
        record, created = await storage.transactions.record_successful_payment(
            bot_id="tenant",
            user_id=7,
            sku_code="vip",
            amount=150,
            telegram_payment_charge_id="chg-old",
            merchant_origin_bot_id="bot-1",
            merchant_telegram_bot_id=101,
        )
        self.assertFalse(created)
        self.assertEqual(record.voucher_id, "v-old")


class TestGate12BodyContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.session = _Session()
        self.bot = Bot(token="42:TEST", session=self.session)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def test_old_factory_call_and_safe_none_defaults(self) -> None:
        config = BotChassisConfig(bot_id="demo", db_path=self.db_path)
        chassis = await create_complete_chassis(self.bot, config)
        self.assertEqual(
            [router.name for router in chassis.dp.sub_routers],
            ["admin", "payments", "localization_router", "chassis_start", "button_chassis"],
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=_private(8, "/start")))
        texts = [item.text for item in _texts(self.session) if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(len(texts), 1)
        self.assertIn("Главное меню", texts[0])

    async def test_one_start_one_info_locale_keeps_domain_donations_and_membership(self) -> None:
        starts: list[str] = []
        infos: list[int] = []
        domain = {"step": 3, "answers": ["a", "b"]}

        async def render_start(context) -> ChassisScreen:
            starts.append(context.locale)
            return ChassisScreen(text="START CARD", markup=None)

        async def render_info(message, user_id, bot) -> ChassisScreen:
            infos.append(user_id)
            return ChassisScreen(text="INFO CARD", markup=None)

        async def on_locale_changed(context) -> None:
            domain["locale"] = context.locale

        catalog = (
            SkuItem("d50", "50", "d", 50, False),
            SkuItem("d100", "100", "d", 100, False),
        )
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            welcome_text="Носитель",
            enable_admin=False,
            enable_payments=True,
            enable_language_switch=True,
            skus=(SkuItem("vip", "VIP", "paid", 150, True),),
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            render_start_callback=render_start,
            render_info_callback=render_info,
            on_locale_changed=on_locale_changed,
            donation_catalog=catalog,
            backup_policy=None,
            reporting_policy=None,
            process_control=None,
        )
        user = _user(11, "ru")
        await chassis.storage.users.record_telegram_visit("bot_a", 11, None, "N", None, "ru", "ru")
        chassis.locale_cache[11] = "ru"

        await chassis.dp.feed_update(
            self.bot,
            Update(update_id=1, message=_private(11, "/start")),
        )
        start_texts = [item.text for item in _texts(self.session) if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(starts, ["ru"])
        self.assertEqual(start_texts, ["Носитель", "START CARD"])

        self.session.requests.clear()
        await chassis.dp.feed_update(
            self.bot,
            Update(update_id=2, message=_private(11, BTN_INFO_RU, 2)),
        )
        info_sends = [item for item in _texts(self.session) if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(infos, [11])
        self.assertEqual([item.text for item in info_sends], ["INFO CARD"])
        toggle = info_sends[0].reply_markup.inline_keyboard[-1][0]
        self.assertEqual(toggle.callback_data, "core_lang:toggle")

        card = Message(
            message_id=self.session.requests.index(info_sends[0]) + 1,
            date=1,
            chat=Chat(id=11, type="private"),
            from_user=user,
            text="INFO CARD",
            reply_markup=info_sends[0].reply_markup,
        )
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=3,
                callback_query=CallbackQuery(
                    id="c3",
                    from_user=user,
                    chat_instance="x",
                    data="core_lang:toggle",
                    message=card,
                ),
            ),
        )
        self.assertEqual(domain, {"step": 3, "answers": ["a", "b"], "locale": "en"})
        stored = await chassis.storage.users.get_user("bot_a", 11)
        self.assertEqual(stored.language_code, "en")
        self.assertEqual(stored.locale_source, "manual")

        self.session.requests.clear()
        await chassis.dp.feed_update(
            self.bot,
            Update(update_id=4, message=_private(11, BTN_SUPPORT_RU, 4)),
        )
        donate_panel = next(item for item in _texts(self.session) if "Выберите действие" in (item.text or ""))
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=5,
                callback_query=CallbackQuery(
                    id="c5",
                    from_user=user,
                    chat_instance="x",
                    data="core_sup:donate",
                    message=Message(
                        message_id=self.session.requests.index(donate_panel) + 1,
                        date=1,
                        chat=Chat(id=11, type="private"),
                        from_user=user,
                        text=donate_panel.text,
                        reply_markup=donate_panel.reply_markup,
                    ),
                ),
            ),
        )
        donate = next(item for item in _texts(self.session) if "Поддержать проект" in (item.text or ""))
        donate_cb = [
            button.callback_data
            for row in donate.reply_markup.inline_keyboard
            for button in row
        ]
        self.assertEqual(donate_cb[:2], ["buy_sku:d50", "buy_sku:d100"])
        self.assertNotIn("buy_sku:vip", donate_cb)

        kicked = ChatMemberUpdated(
            chat=Chat(id=11, type="private"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberMember(user=user),
            new_chat_member=ChatMemberBanned(user=user, until_date=datetime.now(timezone.utc)),
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=6, my_chat_member=kicked))
        statuses = await chassis.storage.bot_statuses.list_for_user("bot_a", 11)
        self.assertEqual(statuses[0].status, "stopped")

        seen: list[str] = []
        sink = logger.add(lambda message: seen.append(str(message)), level="WARNING")
        try:
            warn_if_my_chat_member_missing(("message", "callback_query"))
        finally:
            logger.remove(sink)
        self.assertEqual(len(seen), 1)
        self.assertIn("my_chat_member", seen[0])


class TestGate12Network(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "net.db")
        self.bots: list[Bot] = []

    async def asyncTearDown(self) -> None:
        for bot in self.bots:
            await bot.session.close()
        self._tmp.cleanup()

    async def test_seven_processes_share_tenant_and_keep_origin_status(self) -> None:
        chassis_by_origin = {}
        for index, origin in enumerate(ORIGINS, start=1):
            bot = Bot(token=f"{100000 + index}:TEST", session=_Session())
            self.bots.append(bot)
            config = BotChassisConfig(
                bot_id="tenant",
                db_path=self.db_path,
                origin_bot_id=origin,
                enable_admin=False,
                enable_payments=False,
            )
            chassis = await create_complete_chassis(bot, config)
            await chassis.storage.users.upsert_user("tenant", 7, username="ann")
            await chassis.storage.bot_statuses.mark_active("tenant", 7, origin, int(bot.id))
            chassis_by_origin[origin] = chassis

        solo = Bot(token="42:SOLO", session=_Session())
        self.bots.append(solo)
        single = await create_complete_chassis(
            solo,
            BotChassisConfig(bot_id="solo", db_path=os.path.join(self._tmp.name, "solo.db")),
        )
        await single.dp.feed_update(solo, Update(update_id=1, message=_private(9, "/start")))
        self.assertEqual(len(_texts(solo.session)), 1)

        storage = chassis_by_origin["bot-1"].storage
        self.assertEqual((await storage.users.get_user("tenant", 7)).username, "ann")
        rows = await storage.bot_statuses.list_for_user("tenant", 7)
        self.assertEqual({row.origin_bot_id for row in rows}, set(ORIGINS))
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row.status == "active" for row in rows))
        self.assertEqual(
            {int(bot.id) for bot in self.bots[:7]},
            {row.telegram_bot_id for row in rows},
        )


if __name__ == "__main__":
    unittest.main()
