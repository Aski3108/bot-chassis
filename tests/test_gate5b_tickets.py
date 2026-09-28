"""Gate 5B: continuable SQLite tickets, close/reopen, legacy JSON stays one-shot."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from bot_chassis.storage.engine import StorageEngine
from bot_chassis.storage.sqlite_support_thread_store import (
    SqliteSupportThreadStore,
    TicketLimitExceeded,
)
from bot_chassis.support_bridge import (
    SupportThreadStore,
    deliver_support_reply_to_user,
    send_user_followup_to_support,
    send_user_report_to_support,
)


class _Bot:
    def __init__(self, bot_id: int) -> None:
        self.id = bot_id
        self.sent: list[tuple] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_message_id = 100

    async def send_message(self, chat_id: int, text: str, **_kwargs):
        self.sent.append(("send", chat_id, text, _kwargs.get("reply_markup")))
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int, **_kwargs):
        self.sent.append(("copy", chat_id, message_id))
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, **_kwargs):
        self.sent.append(("edit", chat_id, text))
        return SimpleNamespace(message_id=message_id)

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, **_kwargs):
        self.sent.append(("markup", chat_id, message_id))
        return True


def _reply(chat_id: int, message_id: int, reply_to: int, thread_id=None):
    payload = {
        "chat": SimpleNamespace(id=chat_id),
        "message_id": message_id,
        "from_user": SimpleNamespace(id=14),
        "reply_to_message": SimpleNamespace(message_id=reply_to, message_thread_id=thread_id),
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    return SimpleNamespace(**payload)


class TestGate5BTickets(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        await StorageEngine(self.db_path).initialize()
        self.store = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
        )

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_answered_migrates_to_closed_and_messages_have_no_body(self) -> None:
        legacy = os.path.join(self._tmp.name, "legacy.db")
        conn = sqlite3.connect(legacy)
        try:
            conn.execute(
                """
                CREATE TABLE users (
                    bot_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    language_code TEXT NOT NULL DEFAULT 'ru',
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    is_shadow_banned INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (bot_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE support_threads (
                    bot_id TEXT NOT NULL,
                    support_chat_id INTEGER NOT NULL,
                    support_message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    origin_bot_id TEXT NOT NULL DEFAULT '',
                    origin_telegram_bot_id INTEGER NOT NULL DEFAULT 0,
                    ticket_id TEXT NOT NULL DEFAULT '',
                    message_role TEXT NOT NULL DEFAULT 'header',
                    ticket_status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, support_chat_id, support_message_id)
                )
                """
            )
            conn.execute("INSERT INTO users (bot_id, user_id) VALUES ('psybot', 7)")
            conn.execute(
                """
                INSERT INTO support_threads (
                    bot_id, support_chat_id, support_message_id, user_id,
                    origin_bot_id, origin_telegram_bot_id, ticket_id,
                    message_role, ticket_status
                ) VALUES ('psybot', -100, 10, 7, 'bpd', 101, 'old-1', 'header', 'answered')
                """
            )
            conn.commit()
        finally:
            conn.close()

        engine = StorageEngine(legacy)
        await engine.initialize()
        await engine.initialize()

        def inspect(conn):
            status = conn.execute(
                "SELECT ticket_status FROM support_threads WHERE ticket_id = 'old-1'"
            ).fetchone()[0]
            cols = {row[1] for row in conn.execute("PRAGMA table_info(support_threads)")}
            msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(support_ticket_messages)")}
            return status, cols, msg_cols

        status, cols, msg_cols = await engine.run(inspect)
        self.assertEqual(status, "closed")
        self.assertTrue(
            {"message_thread_id", "operator_id", "first_answered_at", "closed_at"} <= cols
        )
        self.assertEqual(
            msg_cols,
            {
                "bot_id",
                "ticket_id",
                "direction",
                "telegram_chat_id",
                "telegram_message_id",
                "message_thread_id",
                "created_at",
            },
        )
        self.assertNotIn("text", msg_cols)
        self.assertNotIn("body", msg_cols)
        self.assertNotIn("content", msg_cols)

    async def test_operator_can_reply_several_times_without_freeing_slot(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        self.assertTrue(self.store.can_send_ticket(7))
        bot = _Bot(101)
        first = await deliver_support_reply_to_user(bot, _reply(-100, 500, 11), self.store)
        self.assertTrue(first[0])
        self.assertEqual(self.store.resolve_ticket(-100, 10).ticket_status, "in_progress")
        limited = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
            max_active_tickets_per_user=1,
        )
        self.assertFalse(limited.can_send_ticket(7))
        second = await deliver_support_reply_to_user(bot, _reply(-100, 501, 11), self.store)
        self.assertTrue(second[0])
        self.assertEqual(self.store.resolve_ticket(-100, 10).ticket_status, "in_progress")
        self.assertFalse(limited.can_send_ticket(7))
        user_headers = [item for item in bot.sent if item[0] == "send" and item[1] == 7]
        self.assertEqual(len(user_headers), 2)
        self.assertTrue(any("Ответить поддержке" in str(item[3]) for item in user_headers))
        edits = [item for item in bot.sent if item[0] == "edit"]
        self.assertTrue(any("В работе" in item[2] for item in edits))

    async def test_user_followup_bypasses_new_ticket_limit(self) -> None:
        limited = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
            max_active_tickets_per_user=1,
        )
        limited.register(-100, 7, 10, 11, ticket_id="t1")
        self.assertFalse(limited.can_send_ticket(7))
        with self.assertRaises(TicketLimitExceeded):
            limited.register(-100, 7, 20, 21, ticket_id="t2")
        bot = _Bot(101)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username="ann", full_name="Ann"),
            chat=SimpleNamespace(id=7),
            message_id=80,
        )
        copied = await send_user_followup_to_support(bot, user_message, limited, "t1")
        self.assertIsNotNone(copied)
        self.assertEqual(limited.resolve_ticket(-100, copied).ticket_id, "t1")
        self.assertFalse(limited.can_send_ticket(7))

    async def test_five_active_dialogs_continue_and_sixth_new_is_blocked(self) -> None:
        for index in range(5):
            self.store.register(
                -100,
                7,
                10 + index * 2,
                11 + index * 2,
                ticket_id=f"t{index}",
            )
        self.assertFalse(self.store.can_send_ticket(7))
        bot = _Bot(101)
        for index in range(5):
            ok, _status = await deliver_support_reply_to_user(
                bot,
                _reply(-100, 500 + index, 11 + index * 2),
                self.store,
            )
            self.assertTrue(ok)
            user_message = SimpleNamespace(
                from_user=SimpleNamespace(id=7),
                chat=SimpleNamespace(id=7),
                message_id=800 + index,
            )
            copied = await send_user_followup_to_support(
                bot, user_message, self.store, f"t{index}"
            )
            self.assertIsNotNone(copied)
        self.assertFalse(self.store.can_send_ticket(7))
        with self.assertRaises(TicketLimitExceeded):
            self.store.register(-100, 7, 90, 91, ticket_id="t6")

    async def test_close_frees_slot_reopen_occupies_or_hits_limit(self) -> None:
        limited = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
            max_active_tickets_per_user=1,
        )
        limited.register(-100, 7, 10, 11, ticket_id="t1")
        self.assertFalse(limited.can_send_ticket(7))
        self.assertEqual(limited.close_ticket("t1"), 2)
        self.assertEqual(limited.get_ticket("t1").ticket_status, "closed")
        self.assertTrue(limited.can_send_ticket(7))
        self.assertEqual(limited.reopen_ticket("t1"), 2)
        self.assertEqual(limited.get_ticket("t1").ticket_status, "in_progress")
        self.assertFalse(limited.can_send_ticket(7))
        limited.close_ticket("t1")
        limited.register(-100, 7, 20, 21, ticket_id="t2")
        with self.assertRaises(TicketLimitExceeded):
            limited.reopen_ticket("t1")
        self.assertEqual(limited.get_ticket("t1").ticket_status, "closed")

    async def test_wrong_origin_chat_and_topic_are_silent(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1", message_thread_id=11)
        foreign = _Bot(202)
        ok, status = await deliver_support_reply_to_user(
            foreign, _reply(-100, 500, 11, thread_id=11), self.store
        )
        self.assertFalse(ok)
        self.assertEqual(status, "FOREIGN_ORIGIN")
        self.assertEqual(foreign.sent, [])

        origin = _Bot(101)
        ok, status = await deliver_support_reply_to_user(
            origin, _reply(-999, 500, 11, thread_id=11), self.store
        )
        self.assertFalse(ok)
        self.assertEqual(status, "UNKNOWN_THREAD")

        ok, status = await deliver_support_reply_to_user(
            origin, _reply(-100, 501, 11, thread_id=99), self.store
        )
        self.assertFalse(ok)
        self.assertEqual(status, "WRONG_THREAD")
        self.assertEqual(origin.sent, [])

    async def test_restarted_process_keeps_in_progress_ticket(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        await deliver_support_reply_to_user(bot, _reply(-100, 500, 11), self.store)
        revived = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
        )
        ticket = revived.get_ticket("t1")
        self.assertEqual(ticket.ticket_status, "in_progress")
        ok, _status = await deliver_support_reply_to_user(
            _Bot(101), _reply(-100, 502, 11), revived
        )
        self.assertTrue(ok)

    async def test_legacy_json_store_stays_one_shot(self) -> None:
        store = SupportThreadStore(persistence_file=None, max_active_tickets_per_user=1)
        self.assertFalse(store.supports_continuation)
        store.register(-100, 7, 10, 11)
        self.assertFalse(store.can_send_ticket(7))
        bot = _Bot(1)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username="ann", full_name="Ann"),
            chat=SimpleNamespace(id=7),
            message_id=50,
        )
        copied = await send_user_report_to_support(bot, -100, user_message, store)
        self.assertIsNone(copied)
        origin = _Bot(1)
        ok, _status = await deliver_support_reply_to_user(
            origin, _reply(-100, 500, 10), store
        )
        self.assertTrue(ok)
        self.assertTrue(store.can_send_ticket(7))
        self.assertFalse(any(item[0] == "edit" for item in origin.sent))
        user_sends = [item for item in origin.sent if item[0] == "send" and item[1] == 7]
        self.assertTrue(user_sends)
        self.assertIsNone(user_sends[0][3])
        self.assertFalse(hasattr(store, "close_ticket"))
        follow = await send_user_followup_to_support(
            origin,
            SimpleNamespace(from_user=SimpleNamespace(id=7), chat=SimpleNamespace(id=7), message_id=9),
            store,
            "missing",
        )
        self.assertIsNone(follow)


if __name__ == "__main__":
    unittest.main()
