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
    _MAX_CAPTION,
    _MAX_MESSAGE_TEXT,
    compose_support_reply,
    deliver_support_reply_to_user,
    operator_card_text,
    refresh_operator_card,
    send_user_followup_to_support,
    send_user_report_to_support,
)

_DEFAULT_HEADER = "💬 <b>Ответ службы поддержки:</b>"


class _Bot:
    def __init__(self, bot_id: int) -> None:
        self.id = bot_id
        self.sent: list[tuple] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_message_id = 100

    async def send_message(self, chat_id: int, text: str, **_kwargs):
        self.sent.append(("send", chat_id, text, _kwargs.get("reply_markup"), _kwargs))
        message = SimpleNamespace(message_id=self._next_message_id)
        self._next_message_id += 1
        return message

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int, **_kwargs):
        self.sent.append(("copy", chat_id, message_id, _kwargs))
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


def _reply(chat_id: int, message_id: int, reply_to: int, thread_id=None, **extra):
    payload = {
        "chat": SimpleNamespace(id=chat_id),
        "message_id": message_id,
        "from_user": SimpleNamespace(id=14),
        "reply_to_message": SimpleNamespace(message_id=reply_to, message_thread_id=thread_id),
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    payload.update(extra)
    return SimpleNamespace(**payload)


def _user_outbound(bot: _Bot, user_id: int = 7) -> list[tuple]:
    return [item for item in bot.sent if item[0] in {"send", "copy"} and item[1] == user_id]


def _recorded_user_message_ids(db_path: str, ticket_id: str, user_id: int) -> list[int]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT telegram_message_id
            FROM support_ticket_messages
            WHERE ticket_id = ? AND telegram_chat_id = ? AND direction = 'support_to_user'
            ORDER BY rowid
            """,
            (ticket_id, user_id),
        ).fetchall()
    finally:
        conn.close()
    return [int(row[0]) for row in rows]


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

    async def test_operator_card_keeps_author_in_all_statuses(self) -> None:
        bot = _Bot(101)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username="ann", full_name="Anna Test"),
            chat=SimpleNamespace(id=7),
            message_id=50,
        )
        copied = await send_user_report_to_support(
            bot, -100, user_message, self.store, project_label="PsyBot"
        )
        self.assertIsNotNone(copied)
        ticket = self.store.resolve_ticket(-100, 100)
        self.assertIsNotNone(ticket)
        ticket_id = ticket.ticket_id

        open_card = operator_card_text(
            "PsyBot",
            7,
            "open",
            full_name=ticket.user_full_name,
            username=ticket.user_username,
        )
        self.assertIn("<b>От:</b>", open_card)
        self.assertIn("Anna Test", open_card)
        self.assertIn("@ann", open_card)

        self.store.close_ticket(ticket_id)
        await refresh_operator_card(bot, self.store, ticket_id, "PsyBot")
        closed_edits = [item[2] for item in bot.sent if item[0] == "edit"]
        self.assertTrue(closed_edits)
        self.assertIn("<b>От:</b>", closed_edits[-1])
        self.assertIn("Anna Test", closed_edits[-1])
        self.assertIn("@ann", closed_edits[-1])
        self.assertIn("обслужено", closed_edits[-1])

        self.store.reopen_ticket(ticket_id)
        await refresh_operator_card(bot, self.store, ticket_id, "PsyBot")
        reopen_edits = [item[2] for item in bot.sent if item[0] == "edit"]
        self.assertIn("<b>От:</b>", reopen_edits[-1])
        self.assertIn("Anna Test", reopen_edits[-1])
        self.assertIn("@ann", reopen_edits[-1])
        self.assertIn("В работе", reopen_edits[-1])

    async def test_operator_card_without_username(self) -> None:
        bot = _Bot(101)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username=None, full_name="No Nick"),
            chat=SimpleNamespace(id=7),
            message_id=50,
        )
        copied = await send_user_report_to_support(
            bot, -100, user_message, self.store, project_label="PsyBot"
        )
        self.assertIsNotNone(copied)
        ticket = self.store.get_ticket(self.store.resolve_ticket(-100, 100).ticket_id)
        card = operator_card_text(
            "PsyBot",
            ticket.user_id,
            ticket.ticket_status,
            full_name=ticket.user_full_name,
            username=ticket.user_username,
        )
        self.assertIn("нет username", card)
        self.assertIn("No Nick", card)
        header = next(item[2] for item in bot.sent if item[0] == "send")
        self.assertIn("нет username", header)

    async def test_author_name_is_stored_raw_and_escaped_once(self) -> None:
        bot = _Bot(101)
        raw_name = "A & B <C>"
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username="amp", full_name=raw_name),
            chat=SimpleNamespace(id=7),
            message_id=50,
        )
        copied = await send_user_report_to_support(
            bot, -100, user_message, self.store, project_label="PsyBot"
        )
        self.assertIsNotNone(copied)
        ticket = self.store.resolve_ticket(-100, 100)
        self.assertEqual(ticket.user_full_name, raw_name)

        conn = sqlite3.connect(self.db_path)
        try:
            stored = conn.execute(
                "SELECT user_full_name FROM support_threads WHERE ticket_id = ?",
                (ticket.ticket_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(stored, raw_name)
        self.assertNotIn("&amp;", stored)

        header = next(item[2] for item in bot.sent if item[0] == "send")
        self.assertIn("A &amp; B &lt;C&gt;", header)
        self.assertNotIn("A &amp;amp; B", header)

        await refresh_operator_card(bot, self.store, ticket.ticket_id, "PsyBot")
        edited = next(item[2] for item in bot.sent if item[0] == "edit")
        self.assertIn("A &amp; B &lt;C&gt;", edited)
        self.assertNotIn("A &amp;amp; B", edited)

    async def test_operator_card_blank_line_before_status(self) -> None:
        text = operator_card_text(
            "PsyBot",
            7,
            "open",
            full_name="Ann",
            username="ann",
        )
        self.assertIn("\n\n<b>Статус:</b>", text)

    async def test_legacy_custom_thread_store_without_author_kwargs(self) -> None:
        calls: list[dict] = []

        class LegacyStore:
            supports_continuation = False
            max_active_tickets = 5

            def can_send_ticket(self, user_id: int) -> bool:
                return True

            def register(
                self,
                chat_id: int,
                user_id: int,
                header_msg_id: int,
                copied_msg_id=None,
                ticket_id=None,
                message_thread_id=None,
            ) -> None:
                calls.append(
                    {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "header_msg_id": header_msg_id,
                        "copied_msg_id": copied_msg_id,
                        "ticket_id": ticket_id,
                        "message_thread_id": message_thread_id,
                    }
                )

            def mark_answered(self, user_id: int) -> None:
                return None

        bot = _Bot(1)
        user_message = SimpleNamespace(
            from_user=SimpleNamespace(id=7, username="ann", full_name="Ann"),
            chat=SimpleNamespace(id=7),
            message_id=50,
        )
        copied = await send_user_report_to_support(bot, -100, user_message, LegacyStore())
        self.assertIsNotNone(copied)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("full_name", calls[0])
        self.assertNotIn("username", calls[0])

        class ExplodingStore(LegacyStore):
            def register(
                self,
                chat_id: int,
                user_id: int,
                header_msg_id: int,
                copied_msg_id=None,
                ticket_id=None,
                message_thread_id=None,
            ) -> None:
                calls.append({"boom": True})
                raise TypeError("internal store failure")

        boom_calls_before = len(calls)
        bot2 = _Bot(1)
        result = await send_user_report_to_support(bot2, -100, user_message, ExplodingStore())
        self.assertIsNone(result)
        self.assertEqual(len(calls), boom_calls_before + 1)

    async def test_text_reply_arrives_as_single_message(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(
                -100,
                500,
                11,
                text="Оператор отвечает",
                html_text="Оператор отвечает",
            ),
            self.store,
        )
        self.assertTrue(ok)
        outbound = _user_outbound(bot)
        self.assertEqual(len(outbound), 1)
        kind, chat_id, text, markup, kwargs = outbound[0]
        self.assertEqual(kind, "send")
        self.assertEqual(chat_id, 7)
        self.assertIn(_DEFAULT_HEADER, text)
        self.assertIn("Оператор отвечает", text)
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIn("core_sup:ureply:", str(markup))

    async def test_media_with_caption_arrives_as_single_message(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(
                -100,
                500,
                11,
                photo=[SimpleNamespace(file_id="p1")],
                caption="Подпись фото",
                html_caption="Подпись фото",
            ),
            self.store,
        )
        self.assertTrue(ok)
        outbound = _user_outbound(bot)
        self.assertEqual(len(outbound), 1)
        kind, chat_id, message_id, kwargs = outbound[0]
        self.assertEqual(kind, "copy")
        self.assertEqual(chat_id, 7)
        self.assertEqual(message_id, 500)
        self.assertIn(_DEFAULT_HEADER, kwargs["caption"])
        self.assertIn("Подпись фото", kwargs["caption"])
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIn("core_sup:ureply:", str(kwargs.get("reply_markup")))

    async def test_voice_without_caption_still_single_message(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(
                -100,
                500,
                11,
                voice=SimpleNamespace(file_id="v1"),
                caption=None,
                html_caption=None,
            ),
            self.store,
        )
        self.assertTrue(ok)
        outbound = _user_outbound(bot)
        self.assertEqual(len(outbound), 1)
        kind, _chat_id, _message_id, kwargs = outbound[0]
        self.assertEqual(kind, "copy")
        self.assertEqual(kwargs["caption"], _DEFAULT_HEADER)
        self.assertIn("core_sup:ureply:", str(kwargs.get("reply_markup")))

    async def test_sticker_reply_keeps_two_messages(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(
                -100,
                500,
                11,
                sticker=SimpleNamespace(file_id="s1"),
            ),
            self.store,
        )
        self.assertTrue(ok)
        outbound = _user_outbound(bot)
        self.assertEqual(len(outbound), 2)
        self.assertEqual(outbound[0][0], "send")
        self.assertEqual(outbound[0][2], _DEFAULT_HEADER)
        self.assertIn("core_sup:ureply:", str(outbound[0][3]))
        self.assertEqual(outbound[1][0], "copy")
        self.assertEqual(outbound[1][2], 500)
        self.assertNotIn("caption", outbound[1][3])

    async def test_html_metacharacters_are_safe(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(
                -100,
                500,
                11,
                text="A < B & C > D",
                html_text="A &lt; B &amp; C &gt; D <b>bold</b>",
            ),
            self.store,
        )
        self.assertTrue(ok)
        text_out = _user_outbound(bot)[0][2]
        self.assertIn("A &lt; B &amp; C &gt; D <b>bold</b>", text_out)
        self.assertNotIn("A < B & C > D", text_out)

        bot2 = _Bot(101)
        self.store.register(-100, 8, 20, 21, ticket_id="t2")
        ok, _status = await deliver_support_reply_to_user(
            bot2,
            _reply(
                -100,
                501,
                21,
                photo=[SimpleNamespace(file_id="p1")],
                caption="x < y & z",
                html_caption="x &lt; y &amp; z <i>note</i>",
            ),
            self.store,
        )
        self.assertTrue(ok)
        caption = _user_outbound(bot2, user_id=8)[0][3]["caption"]
        self.assertIn("x &lt; y &amp; z <i>note</i>", caption)
        self.assertNotIn("x < y & z", caption)

    async def test_media_group_uses_split_mode(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(
                -100,
                500,
                11,
                photo=[SimpleNamespace(file_id="p1")],
                caption="альбом",
                html_caption="альбом",
                media_group_id="mg-1",
            ),
            self.store,
        )
        self.assertTrue(ok)
        outbound = _user_outbound(bot)
        self.assertEqual(len(outbound), 2)
        self.assertEqual(outbound[0][0], "send")
        self.assertEqual(outbound[1][0], "copy")
        self.assertNotIn("caption", outbound[1][3])

    async def test_over_limit_reply_uses_split_without_truncation(self) -> None:
        self.store.register(-100, 7, 10, 11, ticket_id="t1")
        bot = _Bot(101)
        text_body = "T" * (_MAX_MESSAGE_TEXT - len(_DEFAULT_HEADER) - 1)
        html_text = text_body
        self.assertGreater(len(f"{_DEFAULT_HEADER}\n\n{html_text}"), _MAX_MESSAGE_TEXT)
        ok, _status = await deliver_support_reply_to_user(
            bot,
            _reply(-100, 500, 11, text=text_body, html_text=html_text),
            self.store,
        )
        self.assertTrue(ok)
        outbound = _user_outbound(bot)
        self.assertEqual(len(outbound), 2)
        self.assertEqual(outbound[0][0], "send")
        self.assertEqual(outbound[0][2], _DEFAULT_HEADER)
        self.assertEqual(outbound[1][0], "copy")
        self.assertEqual(outbound[1][2], 500)
        self.assertNotIn("caption", outbound[1][3])

        bot2 = _Bot(101)
        self.store.register(-100, 8, 20, 21, ticket_id="t2")
        caption_body = "C" * (_MAX_CAPTION - len(_DEFAULT_HEADER) - 1)
        self.assertGreater(len(f"{_DEFAULT_HEADER}\n\n{caption_body}"), _MAX_CAPTION)
        ok, _status = await deliver_support_reply_to_user(
            bot2,
            _reply(
                -100,
                501,
                21,
                photo=[SimpleNamespace(file_id="p1")],
                caption=caption_body,
                html_caption=caption_body,
            ),
            self.store,
        )
        self.assertTrue(ok)
        outbound2 = _user_outbound(bot2, user_id=8)
        self.assertEqual(len(outbound2), 2)
        self.assertEqual(outbound2[0][0], "send")
        self.assertEqual(outbound2[1][0], "copy")
        self.assertEqual(outbound2[1][2], 501)
        self.assertNotIn("caption", outbound2[1][3])

    async def test_single_message_mode_records_ticket_message(self) -> None:
        cases = [
            ("text-t", {"text": "hi", "html_text": "hi"}, "send"),
            (
                "caption-t",
                {
                    "photo": [SimpleNamespace(file_id="p1")],
                    "caption": "cap",
                    "html_caption": "cap",
                },
                "copy",
            ),
            ("split-t", {"sticker": SimpleNamespace(file_id="s1")}, "copy"),
        ]
        for index, (ticket_id, extra, delivered_kind) in enumerate(cases):
            header_id = 10 + index * 2
            copy_id = 11 + index * 2
            admin_id = 500 + index
            user_id = 70 + index
            self.store.register(-100, user_id, header_id, copy_id, ticket_id=ticket_id)
            bot = _Bot(101)
            ok, _status = await deliver_support_reply_to_user(
                bot,
                _reply(-100, admin_id, copy_id, **extra),
                self.store,
            )
            self.assertTrue(ok)
            self.assertEqual(
                self.store.get_ticket(ticket_id).ticket_status,
                "in_progress",
            )
            outbound = _user_outbound(bot, user_id=user_id)
            if delivered_kind == "send":
                delivered_msg_id = 100  # first outbound from fresh _Bot
                self.assertEqual(outbound[0][0], "send")
            else:
                # split: header send=100, copy=101; caption: copy=100
                if outbound[0][0] == "send":
                    delivered_msg_id = 101
                else:
                    delivered_msg_id = 100
            recorded = _recorded_user_message_ids(self.db_path, ticket_id, user_id)
            self.assertIn(delivered_msg_id, recorded)
            self.assertTrue(self.store.message_recorded(-100, admin_id))


class TestComposeSupportReply(unittest.TestCase):
    def test_compose_support_reply_modes(self) -> None:
        header = _DEFAULT_HEADER
        mode, payload = compose_support_reply(
            SimpleNamespace(text="hello", html_text="hello"),
            header,
        )
        self.assertEqual(mode, "text")
        self.assertEqual(payload, f"{header}\n\nhello")

        mode, payload = compose_support_reply(
            SimpleNamespace(
                photo=[SimpleNamespace(file_id="p")],
                html_caption="cap",
            ),
            header,
        )
        self.assertEqual(mode, "caption")
        self.assertEqual(payload, f"{header}\n\ncap")

        mode, payload = compose_support_reply(
            SimpleNamespace(voice=SimpleNamespace(file_id="v"), html_caption=None),
            header,
        )
        self.assertEqual(mode, "caption")
        self.assertEqual(payload, header)

        mode, payload = compose_support_reply(
            SimpleNamespace(sticker=SimpleNamespace(file_id="s")),
            header,
        )
        self.assertEqual(mode, "split")
        self.assertIsNone(payload)

        mode, payload = compose_support_reply(
            SimpleNamespace(
                photo=[SimpleNamespace(file_id="p")],
                html_caption="x",
                media_group_id="g1",
            ),
            header,
        )
        self.assertEqual(mode, "split")
        self.assertIsNone(payload)

        huge = "X" * (_MAX_MESSAGE_TEXT)
        mode, payload = compose_support_reply(
            SimpleNamespace(text=huge, html_text=huge),
            header,
        )
        self.assertEqual(mode, "split")
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
