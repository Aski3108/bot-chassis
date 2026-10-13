"""Gate 3: статус каждого бота отдельно от санкции сети."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import (
    Chat,
    ChatMemberBanned,
    ChatMemberMember,
    ChatMemberUpdated,
    Message,
    Update,
    User,
)
from loguru import logger

from bot_chassis.admin.router import _dossier
from bot_chassis.config import BotChassisConfig
from bot_chassis.factory import create_complete_chassis
from bot_chassis.middleware.user_activity import UserActivityMiddleware
from bot_chassis.middleware.throttling import ThrottlingMiddleware
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import StorageEngine
from bot_chassis.user_lifecycle import (
    apply_my_chat_member,
    classify_delivery_error,
    record_delivery_outcome,
    register_membership_handler,
    warn_if_my_chat_member_missing,
)


class TestUserLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "life.db")
        self.config = BotChassisConfig(
            bot_id="network",
            db_path=self.db_path,
            origin_bot_id="bpd",
            audit_chat_id=-200,
            events_thread_id=44,
        )
        self.storage = await create_storage(self.config)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_repeat_migration_adds_status_table(self) -> None:
        path = os.path.join(self._tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE users (
                bot_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                language_code TEXT NOT NULL DEFAULT 'ru',
                is_banned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (bot_id, user_id)
            )
            """
        )
        conn.execute("INSERT INTO users (bot_id, user_id, language_code) VALUES ('network', 8, 'ru')")
        conn.commit()
        conn.close()
        engine = StorageEngine(path)
        await engine.initialize()
        await engine.initialize()

        def _read(connection):
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_bot_statuses'"
            ).fetchone()
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(user_bot_statuses)")
            }
            user = connection.execute("SELECT language_code, is_banned FROM users WHERE user_id = 8").fetchone()
            return table is not None, columns, user["language_code"], user["is_banned"]

        present, columns, language, banned = await engine.run(_read)
        self.assertTrue(present)
        self.assertIn("first_launch_notified_at", columns)
        self.assertEqual(language, "ru")
        self.assertEqual(banned, 0)

    async def test_intermediate_gate3_rows_are_backfilled_without_duplicate_launch(self) -> None:
        path = os.path.join(self._tmp.name, "gate3.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE users (
                bot_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                language_code TEXT NOT NULL DEFAULT 'ru',
                is_banned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (bot_id, user_id)
            );
            CREATE TABLE user_bot_statuses (
                bot_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                origin_bot_id TEXT NOT NULL,
                telegram_bot_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                status_changed_at TEXT NOT NULL,
                last_error_code TEXT,
                PRIMARY KEY (bot_id, user_id, telegram_bot_id)
            );
            INSERT INTO users (bot_id, user_id) VALUES ('network', 8);
            INSERT INTO user_bot_statuses VALUES (
                'network', 8, 'bpd', 101, 'active',
                '2026-09-28 10:00:00', '2026-09-28 10:00:00',
                '2026-09-28 10:00:00', NULL
            );
            """
        )
        conn.commit()
        conn.close()

        engine = StorageEngine(path)
        await engine.initialize()
        await engine.initialize()

        def _read(connection):
            return connection.execute(
                "SELECT first_seen_at, first_launch_notified_at FROM user_bot_statuses"
            ).fetchone()

        row = await engine.run(_read)
        self.assertEqual(row["first_launch_notified_at"], row["first_seen_at"])

    async def test_sanctions_stay_network_wide_and_status_stays_per_bot(self) -> None:
        await self.storage.users.upsert_user("network", 7, username="ann")
        await self.storage.bot_statuses.mark_active("network", 7, "bpd", 101)
        await self.storage.bot_statuses.mark_stopped("network", 7, "adhd", 102, "blocked")
        await self.storage.users.set_ban("network", 7, True, "spam")

        user = await self.storage.users.get_user("network", 7)
        self.assertTrue(user.is_banned)
        rows = {item.telegram_bot_id: item.status for item in await self.storage.bot_statuses.list_for_user("network", 7)}
        self.assertEqual(rows, {101: "active", 102: "stopped"})

        other = BotChassisConfig(bot_id="other", db_path=self.db_path, origin_bot_id="solo")
        other_storage = await create_storage(other)
        await other_storage.users.upsert_user("other", 7)
        await other_storage.bot_statuses.mark_active("other", 7, "solo", 101)
        await record_delivery_outcome(
            self.storage,
            self.config,
            user_id=7,
            telegram_bot_id=101,
            outcome="deleted",
        )
        own = {item.telegram_bot_id: item.status for item in await self.storage.bot_statuses.list_for_user("network", 7)}
        foreign = await other_storage.bot_statuses.list_for_user("other", 7)
        self.assertEqual(own, {101: "deleted", 102: "deleted"})
        self.assertEqual(foreign[0].status, "active")
        self.assertTrue((await self.storage.users.get_user("network", 7)).is_banned)

    async def test_first_launch_event_is_not_repeated(self) -> None:
        bot = SimpleNamespace(id=101, send_message=AsyncMock())
        middleware = UserActivityMiddleware(
            "network",
            self.storage,
            self.config,
            bot_display_name_provider=lambda origin, telegram_bot_id: "BPD",
        )
        user = User(id=9, is_bot=False, first_name="Neo", username="neo", language_code="ru-RU")

        async def once(update_id: int, text: str) -> None:
            message = Message(
                message_id=update_id,
                date=1,
                chat=Chat(id=9, type="private"),
                from_user=user,
                text=text,
            )
            await middleware(
                AsyncMock(return_value="ok"),
                Update(update_id=update_id, message=message),
                {"event_from_user": user, "bot": bot},
            )

        await once(1, "/start ref_3")
        await once(2, "/start ref_9")
        self.assertEqual(bot.send_message.await_count, 1)
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["message_thread_id"], 44)
        text = bot.send_message.await_args.args[1]
        self.assertIn("Новый пользователь", text)
        self.assertIn("@neo · ID 9", text)
        self.assertIn("Бот: BPD", text)
        self.assertIn("Источник: ref_3", text)
        self.assertIn("Локаль: ru", text)
        self.assertIn("language_code: ru-RU", text)
        status = await self.storage.bot_statuses.list_for_user("network", 9)
        self.assertEqual(status[0].status, "active")
        self.assertEqual((await self.storage.users.get_user("network", 9)).traffic_source, "ref_3")

    async def test_membership_and_temporary_errors(self) -> None:
        await self.storage.users.upsert_user("network", 7)
        self.storage.bot_statuses.bind_process("bpd", 101)
        bot = SimpleNamespace(id=101, send_message=AsyncMock())
        user = User(id=7, is_bot=False, first_name="N")
        kicked = ChatMemberUpdated(
            chat=Chat(id=7, type="private"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberMember(user=user),
            new_chat_member=ChatMemberBanned(user=user, until_date=datetime.now(timezone.utc)),
        )
        await apply_my_chat_member(self.storage, self.config, kicked, bot=bot)
        self.assertEqual(
            (await self.storage.bot_statuses.list_for_user("network", 7))[0].status,
            "stopped",
        )

        returned = ChatMemberUpdated(
            chat=Chat(id=7, type="private"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberBanned(user=user, until_date=datetime.now(timezone.utc)),
            new_chat_member=ChatMemberMember(user=user),
        )
        await apply_my_chat_member(self.storage, self.config, kicked, bot=bot)
        self.assertEqual(bot.send_message.await_count, 1)

        await apply_my_chat_member(self.storage, self.config, returned, bot=bot)
        self.assertEqual(
            (await self.storage.bot_statuses.list_for_user("network", 7))[0].status,
            "active",
        )
        self.assertEqual(bot.send_message.await_count, 2)
        self.assertIn("возобновил", bot.send_message.await_args.args[1])

        method = SendMessage(chat_id=7, text="x")
        self.assertIsNone(classify_delivery_error(TelegramRetryAfter(method=method, message="flood", retry_after=1)))
        self.assertIsNone(classify_delivery_error(TelegramBadRequest(method=method, message="chat not found")))
        before = (await self.storage.bot_statuses.list_for_user("network", 7))[0].status
        self.assertEqual(before, "active")

        group = ChatMemberUpdated(
            chat=Chat(id=-100, type="supergroup"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberMember(user=user),
            new_chat_member=ChatMemberBanned(user=user, until_date=datetime.now(timezone.utc)),
        )
        await apply_my_chat_member(self.storage, self.config, group)
        self.assertEqual(
            (await self.storage.bot_statuses.list_for_user("network", 7))[0].status,
            "active",
        )

    async def test_membership_before_start_does_not_consume_first_launch_event(self) -> None:
        await self.storage.users.upsert_user("network", 12, username="first")
        bot = SimpleNamespace(id=101, send_message=AsyncMock())
        user = User(id=12, is_bot=False, first_name="N", username="first", language_code="en")
        member = ChatMemberUpdated(
            chat=Chat(id=12, type="private"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberBanned(user=user, until_date=datetime.now(timezone.utc)),
            new_chat_member=ChatMemberMember(user=user),
        )
        await apply_my_chat_member(self.storage, self.config, member, bot=bot)
        self.assertEqual(bot.send_message.await_count, 0)

        middleware = UserActivityMiddleware("network", self.storage, self.config)
        message = Message(
            message_id=1,
            date=1,
            chat=Chat(id=12, type="private"),
            from_user=user,
            text="/start ref_first",
        )
        await middleware(
            AsyncMock(return_value="ok"),
            Update(update_id=1, message=message),
            {"event_from_user": user, "bot": bot},
        )
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertIn("Новый пользователь", bot.send_message.await_args.args[1])

    async def test_membership_update_bypasses_throttling(self) -> None:
        middleware = ThrottlingMiddleware("network")
        user = User(id=13, is_bot=False, first_name="N")
        handled: list[int] = []

        async def handler(event, data):
            handled.append(event.update_id)

        for update_id in range(1, 6):
            await middleware(
                handler,
                Update(update_id=update_id),
                {"event_from_user": user},
            )
        membership = ChatMemberUpdated(
            chat=Chat(id=13, type="private"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberMember(user=user),
            new_chat_member=ChatMemberBanned(user=user, until_date=datetime.now(timezone.utc)),
        )
        await middleware(
            handler,
            Update(update_id=6, my_chat_member=membership),
            {"event_from_user": user},
        )
        self.assertEqual(handled, [1, 2, 3, 4, 5, 6])

    async def test_broadcast_keeps_unknown_and_records_block(self) -> None:
        await self.storage.users.upsert_user("network", 1)
        await self.storage.users.upsert_user("network", 2)
        await self.storage.users.upsert_user("network", 3)
        await self.storage.users.set_ban("network", 3, True, "spam")
        await self.storage.bot_statuses.mark_active("network", 1, "bpd", 101)
        ids = await self.storage.users.get_broadcast_user_ids("network", 101)
        self.assertEqual(ids, [1, 2])

        await record_delivery_outcome(
            self.storage,
            self.config,
            user_id=2,
            telegram_bot_id=101,
            outcome="stopped",
        )
        self.assertEqual(await self.storage.users.get_broadcast_user_ids("network", 101), [1])
        self.assertIn(2, await self.storage.users.get_broadcast_user_ids("network"))
        self.assertEqual(
            classify_delivery_error(
                TelegramForbiddenError(
                    method=SendMessage(chat_id=2, text="x"),
                    message="bot was blocked by the user",
                )
            ),
            "stopped",
        )

    async def test_dossier_shows_sanction_then_bot_table(self) -> None:
        await self.storage.users.upsert_user("network", 7, username="ann")
        await self.storage.users.upsert_user("network", 8)
        await self.storage.bot_statuses.mark_active("network", 7, "bpd", 101)
        await self.storage.bot_statuses.mark_stopped("network", 8, "adhd", 102, "blocked")
        self.storage.bot_statuses.bind_process("profiling", 103)

        def names(origin: str, telegram_bot_id: int) -> str:
            return {101: "BPD", 102: "ADHD", 103: "Profiling"}.get(telegram_bot_id, origin)

        text, _markup = await _dossier(
            self.storage,
            "network",
            7,
            bot_display_name_provider=names,
            telegram_bot_id=101,
        )
        self.assertIn("Статус: 🟢 Активен", text)
        self.assertNotIn("Санкции сети", text)
        self.assertNotIn("BPD", text)
        self.assertNotIn("ADHD", text)
        self.assertNotIn("Profiling", text)

        await self.storage.users.set_ban("network", 7, True, "spam")
        text, _markup = await _dossier(
            self.storage, "network", 7, bot_display_name_provider=names, telegram_bot_id=101
        )
        self.assertIn("Статус: 🔴 Заблокирован", text)
        self.assertNotIn("Санкции сети", text)

    def test_narrow_allowed_updates_are_reported(self) -> None:
        seen: list[str] = []
        sink = logger.add(lambda message: seen.append(str(message)), level="WARNING")
        try:
            warn_if_my_chat_member_missing(None)
            warn_if_my_chat_member_missing(["message", "my_chat_member"])
            warn_if_my_chat_member_missing(["message", "callback_query"])
        finally:
            logger.remove(sink)
        self.assertEqual(len(seen), 1)
        self.assertIn("my_chat_member", seen[0])

    async def test_factory_registers_origin_without_reordering_routers(self) -> None:
        bot = Bot(token="4242:TEST")
        try:
            config = BotChassisConfig(bot_id="bot_a", db_path=self.db_path, origin_bot_id="adhd")
            chassis = await create_complete_chassis(bot, config)
        finally:
            await bot.session.close()
        self.assertEqual(chassis.storage.bot_statuses.process.origin_bot_id, "adhd")
        self.assertEqual(chassis.storage.bot_statuses.process.telegram_bot_id, 4242)
        self.assertEqual(
            [router.name for router in chassis.dp.sub_routers],
            ["admin", "payments", "localization_router", "chassis_start", "button_chassis"],
        )
        dispatcher = Dispatcher()
        register_membership_handler(dispatcher, self.storage, self.config)
        self.assertEqual(len(dispatcher.my_chat_member.handlers), 1)
