"""Synchronous SQLite-backed support ticket mapping for multi-bot projects."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .engine import utc_now

ACTIVE_TICKET_STATUSES = ("open", "in_progress")
CONTINUATION_STATUSES = ("open", "in_progress")


class TicketLimitExceeded(RuntimeError):
    """The atomic ticket limit rejected a registration after its pre-check."""


@dataclass(slots=True, frozen=True)
class SupportTicketTarget:
    user_id: int
    ticket_id: str
    origin_bot_id: str
    origin_telegram_bot_id: int
    ticket_status: str
    support_chat_id: int = 0
    message_thread_id: int | None = None
    operator_id: int | None = None


class SqliteSupportThreadStore:
    """Duck-type replacement for ``SupportThreadStore`` using shared SQLite."""

    def __init__(
        self,
        db_path: str,
        tenant_bot_id: str,
        origin_bot_id: str,
        origin_telegram_bot_id: int,
        max_active_tickets_per_user: int = 5,
    ) -> None:
        if db_path == ":memory:":
            raise ValueError("SqliteSupportThreadStore requires a persistent database path")
        self._db_path = db_path
        self._tenant_bot_id = tenant_bot_id
        self._origin_bot_id = origin_bot_id
        self._origin_telegram_bot_id = origin_telegram_bot_id
        self.max_active_tickets = max_active_tickets_per_user
        self.supports_continuation = True

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def can_send_ticket(self, user_id: int) -> bool:
        conn = self._connect()
        try:
            return self._count_active_headers(conn, user_id) < self.max_active_tickets
        finally:
            conn.close()

    def register(
        self,
        chat_id: int,
        user_id: int,
        header_msg_id: int,
        copied_msg_id: Optional[int] = None,
        ticket_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
    ) -> str:
        resolved_ticket_id = ticket_id or str(uuid.uuid4())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR IGNORE INTO users (bot_id, user_id, language_code)
                VALUES (?, ?, 'ru')
                """,
                (self._tenant_bot_id, user_id),
            )
            if self._count_active_headers(conn, user_id) >= self.max_active_tickets:
                conn.rollback()
                raise TicketLimitExceeded(
                    f"active support ticket limit reached for user {user_id}"
                )
            self._insert_message(
                conn,
                chat_id=chat_id,
                message_id=header_msg_id,
                user_id=user_id,
                ticket_id=resolved_ticket_id,
                message_role="header",
                ticket_status="open",
                message_thread_id=message_thread_id,
            )
            if copied_msg_id is not None:
                self._insert_message(
                    conn,
                    chat_id=chat_id,
                    message_id=copied_msg_id,
                    user_id=user_id,
                    ticket_id=resolved_ticket_id,
                    message_role="copy",
                    ticket_status="open",
                    message_thread_id=message_thread_id,
                )
                self._record_message(
                    conn,
                    ticket_id=resolved_ticket_id,
                    direction="user_to_support",
                    telegram_chat_id=chat_id,
                    telegram_message_id=copied_msg_id,
                    message_thread_id=message_thread_id,
                )
            conn.commit()
            return resolved_ticket_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def resolve_user(self, chat_id: int, reply_to_message_id: int) -> Optional[int]:
        target = self.resolve_ticket(chat_id, reply_to_message_id)
        return (
            target.user_id
            if target is not None and target.ticket_status in CONTINUATION_STATUSES
            else None
        )

    def mark_answered(self, user_id: int) -> None:
        """Legacy fallback: first reply on the oldest open ticket."""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT ticket_id
                FROM support_threads
                WHERE bot_id = ? AND user_id = ? AND ticket_status = 'open'
                  AND message_role = 'header'
                ORDER BY created_at, support_message_id
                LIMIT 1
                """,
                (self._tenant_bot_id, user_id),
            ).fetchone()
        finally:
            conn.close()
        if row:
            self.mark_in_progress(str(row["ticket_id"]))

    def resolve_ticket(
        self,
        chat_id: int,
        reply_to_message_id: int,
    ) -> Optional[SupportTicketTarget]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT user_id, ticket_id, origin_bot_id, origin_telegram_bot_id,
                       ticket_status, support_chat_id, message_thread_id, operator_id
                FROM support_threads
                WHERE bot_id = ? AND support_chat_id = ? AND support_message_id = ?
                """,
                (self._tenant_bot_id, chat_id, reply_to_message_id),
            ).fetchone()
            return self._row_to_target(row)
        finally:
            conn.close()

    def get_ticket(self, ticket_id: str) -> Optional[SupportTicketTarget]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT user_id, ticket_id, origin_bot_id, origin_telegram_bot_id,
                       ticket_status, support_chat_id, message_thread_id, operator_id
                FROM support_threads
                WHERE bot_id = ? AND ticket_id = ? AND message_role = 'header'
                LIMIT 1
                """,
                (self._tenant_bot_id, ticket_id),
            ).fetchone()
            return self._row_to_target(row)
        finally:
            conn.close()

    def header_message_id(self, ticket_id: str) -> Optional[int]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT support_message_id
                FROM support_threads
                WHERE bot_id = ? AND ticket_id = ? AND message_role = 'header'
                LIMIT 1
                """,
                (self._tenant_bot_id, ticket_id),
            ).fetchone()
            return int(row["support_message_id"]) if row else None
        finally:
            conn.close()

    def mark_ticket_answered(self, ticket_id: str) -> int:
        """Compatibility alias: first operator reply keeps the slot."""
        return self.mark_in_progress(ticket_id)

    def mark_in_progress(
        self,
        ticket_id: str,
        *,
        operator_id: int | None = None,
    ) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = utc_now()
            cursor = conn.execute(
                """
                UPDATE support_threads
                SET ticket_status = 'in_progress',
                    first_answered_at = COALESCE(first_answered_at, ?),
                    operator_id = COALESCE(operator_id, ?),
                    updated_at = ?
                WHERE bot_id = ? AND ticket_id = ? AND ticket_status = 'open'
                """,
                (now, operator_id, now, self._tenant_bot_id, ticket_id),
            )
            changed = int(cursor.rowcount)
            if changed == 0:
                conn.execute(
                    """
                    UPDATE support_threads
                    SET updated_at = ?,
                        operator_id = COALESCE(operator_id, ?)
                    WHERE bot_id = ? AND ticket_id = ? AND ticket_status = 'in_progress'
                    """,
                    (now, operator_id, self._tenant_bot_id, ticket_id),
                )
            conn.commit()
            return changed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close_ticket(self, ticket_id: str) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = utc_now()
            cursor = conn.execute(
                """
                UPDATE support_threads
                SET ticket_status = 'closed',
                    closed_at = ?,
                    updated_at = ?
                WHERE bot_id = ? AND ticket_id = ?
                  AND ticket_status IN ('open', 'in_progress')
                """,
                (now, now, self._tenant_bot_id, ticket_id),
            )
            conn.commit()
            return int(cursor.rowcount)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reopen_ticket(self, ticket_id: str) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            header = conn.execute(
                """
                SELECT user_id, ticket_status
                FROM support_threads
                WHERE bot_id = ? AND ticket_id = ? AND message_role = 'header'
                LIMIT 1
                """,
                (self._tenant_bot_id, ticket_id),
            ).fetchone()
            if header is None or str(header["ticket_status"]) != "closed":
                conn.rollback()
                return 0
            user_id = int(header["user_id"])
            if self._count_active_headers(conn, user_id) >= self.max_active_tickets:
                conn.rollback()
                raise TicketLimitExceeded(
                    f"active support ticket limit reached for user {user_id}"
                )
            now = utc_now()
            cursor = conn.execute(
                """
                UPDATE support_threads
                SET ticket_status = 'in_progress',
                    closed_at = NULL,
                    updated_at = ?
                WHERE bot_id = ? AND ticket_id = ? AND ticket_status = 'closed'
                """,
                (now, self._tenant_bot_id, ticket_id),
            )
            conn.commit()
            return int(cursor.rowcount)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def attach_message(
        self,
        ticket_id: str,
        *,
        chat_id: int,
        message_id: int,
        message_role: str = "copy",
        message_thread_id: int | None = None,
    ) -> None:
        ticket = self.get_ticket(ticket_id)
        if ticket is None or ticket.ticket_status not in CONTINUATION_STATUSES:
            return
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._insert_message(
                conn,
                chat_id=chat_id,
                message_id=message_id,
                user_id=ticket.user_id,
                ticket_id=ticket_id,
                message_role=message_role,
                ticket_status=ticket.ticket_status,
                message_thread_id=message_thread_id
                if message_thread_id is not None
                else ticket.message_thread_id,
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_message(
        self,
        ticket_id: str,
        *,
        direction: str,
        telegram_chat_id: int,
        telegram_message_id: int,
        message_thread_id: int | None = None,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._record_message(
                conn,
                ticket_id=ticket_id,
                direction=direction,
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
                message_thread_id=message_thread_id,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def message_recorded(
        self,
        telegram_chat_id: int,
        telegram_message_id: int,
    ) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT 1
                FROM support_ticket_messages
                WHERE bot_id = ? AND telegram_chat_id = ? AND telegram_message_id = ?
                """,
                (self._tenant_bot_id, telegram_chat_id, telegram_message_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def _row_to_target(self, row: sqlite3.Row | None) -> Optional[SupportTicketTarget]:
        if not row:
            return None
        thread_raw = row["message_thread_id"]
        operator_raw = row["operator_id"]
        return SupportTicketTarget(
            user_id=int(row["user_id"]),
            ticket_id=str(row["ticket_id"]),
            origin_bot_id=str(row["origin_bot_id"]),
            origin_telegram_bot_id=int(row["origin_telegram_bot_id"]),
            ticket_status=str(row["ticket_status"]),
            support_chat_id=int(row["support_chat_id"]),
            message_thread_id=int(thread_raw) if thread_raw is not None else None,
            operator_id=int(operator_raw) if operator_raw is not None else None,
        )

    def _count_active_headers(self, conn: sqlite3.Connection, user_id: int) -> int:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT ticket_id) AS total
            FROM support_threads
            WHERE bot_id = ? AND user_id = ?
              AND ticket_status IN ('open', 'in_progress')
              AND message_role = 'header'
            """,
            (self._tenant_bot_id, user_id),
        ).fetchone()
        return int(row["total"])

    def _insert_message(
        self,
        conn: sqlite3.Connection,
        *,
        chat_id: int,
        message_id: int,
        user_id: int,
        ticket_id: str,
        message_role: str,
        ticket_status: str,
        message_thread_id: int | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO support_threads (
                bot_id, support_chat_id, support_message_id, user_id,
                origin_bot_id, origin_telegram_bot_id, ticket_id,
                message_role, ticket_status, message_thread_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._tenant_bot_id,
                chat_id,
                message_id,
                user_id,
                self._origin_bot_id,
                self._origin_telegram_bot_id,
                ticket_id,
                message_role,
                ticket_status,
                message_thread_id,
                utc_now(),
            ),
        )

    def _record_message(
        self,
        conn: sqlite3.Connection,
        *,
        ticket_id: str,
        direction: str,
        telegram_chat_id: int,
        telegram_message_id: int,
        message_thread_id: int | None,
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO support_ticket_messages (
                bot_id, ticket_id, direction, telegram_chat_id,
                telegram_message_id, message_thread_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._tenant_bot_id,
                ticket_id,
                direction,
                telegram_chat_id,
                telegram_message_id,
                message_thread_id,
                utc_now(),
            ),
        )
