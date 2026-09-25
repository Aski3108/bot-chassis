"""Репозиторий тредов поддержки. На этапе 1 не подключается к SupportThreadStore."""

from __future__ import annotations

from typing import Optional

from ..engine import StorageEngine, utc_now


class SupportThreadsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def register_thread(
        self,
        bot_id: str,
        support_chat_id: int,
        support_message_id: int,
        user_id: int,
        origin_bot_id: str | None = None,
        origin_telegram_bot_id: int = 0,
        ticket_id: str = "",
        message_role: str = "header",
    ) -> None:
        def _op(conn) -> None:
            conn.execute(
                """
                INSERT OR IGNORE INTO support_threads (
                    bot_id, support_chat_id, support_message_id, user_id,
                    origin_bot_id, origin_telegram_bot_id, ticket_id,
                    message_role, ticket_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    bot_id,
                    support_chat_id,
                    support_message_id,
                    user_id,
                    origin_bot_id or bot_id,
                    origin_telegram_bot_id,
                    ticket_id,
                    message_role,
                    utc_now(),
                ),
            )

        await self._engine.run(_op)

    async def count_open_headers(self, bot_id: str, user_id: int) -> int:
        def _op(conn) -> int:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM support_threads
                WHERE bot_id = ? AND user_id = ?
                  AND ticket_status = 'open' AND message_role = 'header'
                """,
                (bot_id, user_id),
            ).fetchone()
            return int(row["total"])

        return await self._engine.run(_op)

    async def resolve_user(
        self,
        bot_id: str,
        support_chat_id: int,
        support_message_id: int,
    ) -> Optional[int]:
        def _op(conn) -> Optional[int]:
            row = conn.execute(
                """
                SELECT user_id FROM support_threads
                WHERE bot_id = ? AND support_chat_id = ? AND support_message_id = ?
                """,
                (bot_id, support_chat_id, support_message_id),
            ).fetchone()
            return int(row["user_id"]) if row else None

        return await self._engine.run(_op)

    async def mark_answered(self, bot_id: str, user_id: int) -> int:
        def _op(conn) -> int:
            cur = conn.execute(
                """
                UPDATE support_threads
                SET ticket_status = 'answered', updated_at = ?
                WHERE bot_id = ? AND user_id = ? AND ticket_status = 'open'
                """,
                (utc_now(), bot_id, user_id),
            )
            return int(cur.rowcount)

        return await self._engine.run(_op)
