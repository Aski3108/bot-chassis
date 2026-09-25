"""Synchronous SQLite-backed support ticket mapping for multi-bot projects."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .engine import utc_now


class TicketLimitExceeded(RuntimeError):
    """The atomic ticket limit rejected a registration after its pre-check."""


@dataclass(slots=True, frozen=True)
class SupportTicketTarget:
    user_id: int
    ticket_id: str
    origin_bot_id: str
    origin_telegram_bot_id: int


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
            return self._count_open_headers(conn, user_id) < self.max_active_tickets
        finally:
            conn.close()

    def register(
        self,
        chat_id: int,
        user_id: int,
        header_msg_id: int,
        copied_msg_id: Optional[int] = None,
        ticket_id: Optional[str] = None,
    ) -> None:
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
            if self._count_open_headers(conn, user_id) >= self.max_active_tickets:
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
            )
            if copied_msg_id is not None:
                self._insert_message(
                    conn,
                    chat_id=chat_id,
                    message_id=copied_msg_id,
                    user_id=user_id,
                    ticket_id=resolved_ticket_id,
                    message_role="copy",
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def resolve_user(self, chat_id: int, reply_to_message_id: int) -> Optional[int]:
        target = self.resolve_ticket(chat_id, reply_to_message_id)
        return target.user_id if target else None

    def mark_answered(self, user_id: int) -> None:
        """Legacy fallback: answer the oldest open ticket for this user."""
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
            self.mark_ticket_answered(str(row["ticket_id"]))

    def resolve_ticket(
        self,
        chat_id: int,
        reply_to_message_id: int,
    ) -> Optional[SupportTicketTarget]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT user_id, ticket_id, origin_bot_id, origin_telegram_bot_id
                FROM support_threads
                WHERE bot_id = ? AND support_chat_id = ? AND support_message_id = ?
                  AND ticket_status = 'open'
                """,
                (self._tenant_bot_id, chat_id, reply_to_message_id),
            ).fetchone()
            if not row:
                return None
            return SupportTicketTarget(
                user_id=int(row["user_id"]),
                ticket_id=str(row["ticket_id"]),
                origin_bot_id=str(row["origin_bot_id"]),
                origin_telegram_bot_id=int(row["origin_telegram_bot_id"]),
            )
        finally:
            conn.close()

    def mark_ticket_answered(self, ticket_id: str) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE support_threads
                SET ticket_status = 'answered', updated_at = ?
                WHERE bot_id = ? AND ticket_id = ? AND ticket_status = 'open'
                """,
                (utc_now(), self._tenant_bot_id, ticket_id),
            )
            conn.commit()
            return int(cursor.rowcount)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _count_open_headers(self, conn: sqlite3.Connection, user_id: int) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM support_threads
            WHERE bot_id = ? AND user_id = ? AND ticket_status = 'open'
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
    ) -> None:
        conn.execute(
            """
            INSERT INTO support_threads (
                bot_id, support_chat_id, support_message_id, user_id,
                origin_bot_id, origin_telegram_bot_id, ticket_id,
                message_role, ticket_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
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
                utc_now(),
            ),
        )
