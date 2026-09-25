"""Shared SQLite support tickets: exact routing, limits, and compensation."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from bot_chassis.storage.engine import StorageEngine
from bot_chassis.storage.sqlite_support_thread_store import (
    SqliteSupportThreadStore,
    TicketLimitExceeded,
)
from bot_chassis.support_bridge import (
    deliver_support_reply_to_user,
    send_user_report_to_support,
)


class _Bot:
    def __init__(self, bot_id: int) -> None:
        self.id = bot_id
        self.sent: list[tuple[str, int, int | str]] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_message_id = 100

    async def send_message(self, chat_id: int, text: str, **_kwargs):
        self.sent.append(("send", chat_id, text))
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int):
        self.sent.append(("copy", chat_id, message_id))
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))


class _RaceStore:
    def can_send_ticket(self, _user_id: int) -> bool:
        return True

    def register(self, **_kwargs) -> None:
        raise TicketLimitExceeded("simulated concurrent registration")


class TestSqliteSupportThreadStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        await StorageEngine(self.db_path).initialize()
        self.bpd = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
        )

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_register_without_user_and_close_only_selected_ticket(self) -> None:
        self.bpd.register(-100, 7, 10, 11, ticket_id="ticket-1")
        self.bpd.register(-100, 7, 20, 21, ticket_id="ticket-2")
        adhd = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="adhd",
            origin_telegram_bot_id=202,
        )
        adhd.register(-100, 7, 30, 31, ticket_id="ticket-3")

        target = self.bpd.resolve_ticket(-100, 11)
        self.assertEqual(target.user_id, 7)
        self.assertEqual(target.ticket_id, "ticket-1")
        self.assertEqual(target.origin_bot_id, "bpd")
        self.assertEqual(target.origin_telegram_bot_id, 101)
        self.assertEqual(self.bpd.mark_ticket_answered("ticket-1"), 2)
        self.assertIsNone(self.bpd.resolve_ticket(-100, 10))
        self.assertEqual(self.bpd.resolve_ticket(-100, 20).ticket_id, "ticket-2")
        self.assertEqual(adhd.resolve_ticket(-100, 30).ticket_id, "ticket-3")
        self.assertEqual(self.bpd.resolve_user(-100, 20), 7)

        def _inspect(conn):
            user = conn.execute(
                "SELECT language_code FROM users WHERE bot_id = ? AND user_id = ?",
                ("psybot", 7),
            ).fetchone()
            open_headers = conn.execute(
                """
                SELECT COUNT(*) FROM support_threads
                WHERE bot_id = 'psybot' AND user_id = 7
                  AND ticket_status = 'open' AND message_role = 'header'
                """
            ).fetchone()[0]
            return user, open_headers

        user, open_headers = await StorageEngine(self.db_path).run(_inspect)
        self.assertEqual(user["language_code"], "ru")
        self.assertEqual(open_headers, 2)

    async def test_foreign_bot_stays_silent_and_origin_closes_exact_ticket(self) -> None:
        self.bpd.register(-100, 7, 10, 11, ticket_id="ticket-1")
        self.bpd.register(-100, 7, 20, 21, ticket_id="ticket-2")
        reply = SimpleNamespace(
            chat=SimpleNamespace(id=-100),
            message_id=500,
            reply_to_message=SimpleNamespace(message_id=11),
        )

        foreign_bot = _Bot(202)
        success, status = await deliver_support_reply_to_user(
            foreign_bot, reply, self.bpd
        )
        self.assertFalse(success)
        self.assertEqual(status, "FOREIGN_ORIGIN")
        self.assertEqual(foreign_bot.sent, [])

        origin_bot = _Bot(101)
        success, _status = await deliver_support_reply_to_user(
            origin_bot, reply, self.bpd
        )
        self.assertTrue(success)
        self.assertEqual(len(origin_bot.sent), 2)
        self.assertIsNone(self.bpd.resolve_ticket(-100, 10))
        self.assertEqual(self.bpd.resolve_ticket(-100, 20).ticket_id, "ticket-2")

    async def test_atomic_limit_and_bridge_compensation(self) -> None:
        limited = SqliteSupportThreadStore(
            self.db_path,
            tenant_bot_id="psybot",
            origin_bot_id="bpd",
            origin_telegram_bot_id=101,
            max_active_tickets_per_user=1,
        )
        limited.register(-100, 7, 10, 11, ticket_id="ticket-1")
        self.assertFalse(limited.can_send_ticket(7))
        with self.assertRaises(TicketLimitExceeded):
            limited.register(-100, 7, 20, 21, ticket_id="ticket-2")

        bot = _Bot(101)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(
                id=8,
                username="ann",
                full_name="Ann Example",
            ),
            chat=SimpleNamespace(id=8),
            message_id=50,
        )
        copied_id = await send_user_report_to_support(
            bot,
            support_chat_id=-100,
            user_message=user_message,
            thread_store=_RaceStore(),
        )
        self.assertIsNone(copied_id)
        self.assertEqual(bot.deleted, [(-100, 101), (-100, 100)])

    async def test_memory_database_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SqliteSupportThreadStore(":memory:", "psybot", "bpd", 101)


if __name__ == "__main__":
    unittest.main()
