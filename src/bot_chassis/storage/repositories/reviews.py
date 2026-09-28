"""Очередь отзывов: только маршрутизация, согласие и статус."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine import StorageEngine, utc_now


@dataclass(slots=True, frozen=True)
class ReviewRecord:
    bot_id: str
    review_id: str
    user_id: int
    origin_bot_id: str
    source_chat_id: int
    source_message_id: int
    moderation_chat_id: int | None
    moderation_message_id: int | None
    published_chat_id: int | None
    published_message_id: int | None
    consent_to_publish: bool
    status: str
    created_at: str
    reviewed_at: str | None
    published_at: str | None


def _row_to_record(row) -> ReviewRecord:
    return ReviewRecord(
        bot_id=str(row["bot_id"]),
        review_id=str(row["review_id"]),
        user_id=int(row["user_id"]),
        origin_bot_id=str(row["origin_bot_id"]),
        source_chat_id=int(row["source_chat_id"]),
        source_message_id=int(row["source_message_id"]),
        moderation_chat_id=int(row["moderation_chat_id"]) if row["moderation_chat_id"] is not None else None,
        moderation_message_id=(
            int(row["moderation_message_id"]) if row["moderation_message_id"] is not None else None
        ),
        published_chat_id=int(row["published_chat_id"]) if row["published_chat_id"] is not None else None,
        published_message_id=(
            int(row["published_message_id"]) if row["published_message_id"] is not None else None
        ),
        consent_to_publish=bool(int(row["consent_to_publish"])),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] is not None else None,
        published_at=str(row["published_at"]) if row["published_at"] is not None else None,
    )


class ReviewSubmissionsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def create(
        self,
        bot_id: str,
        review_id: str,
        user_id: int,
        *,
        origin_bot_id: str,
        source_chat_id: int,
        source_message_id: int,
        consent_to_publish: bool,
        moderation_chat_id: int | None = None,
        moderation_message_id: int | None = None,
    ) -> None:
        def _op(conn) -> None:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (bot_id, user_id, language_code)
                VALUES (?, ?, 'ru')
                """,
                (bot_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO review_submissions (
                    bot_id, review_id, user_id, origin_bot_id,
                    source_chat_id, source_message_id,
                    moderation_chat_id, moderation_message_id,
                    consent_to_publish, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    bot_id,
                    review_id,
                    user_id,
                    origin_bot_id,
                    source_chat_id,
                    source_message_id,
                    moderation_chat_id,
                    moderation_message_id,
                    1 if consent_to_publish else 0,
                    utc_now(),
                ),
            )

        await self._engine.run(_op)

    async def get(self, bot_id: str, review_id: str) -> Optional[ReviewRecord]:
        def _op(conn) -> Optional[ReviewRecord]:
            row = conn.execute(
                """
                SELECT * FROM review_submissions
                WHERE bot_id = ? AND review_id = ?
                """,
                (bot_id, review_id),
            ).fetchone()
            return _row_to_record(row) if row else None

        return await self._engine.run(_op)

    async def mark_published(
        self,
        bot_id: str,
        review_id: str,
        *,
        published_chat_id: int,
        published_message_id: int,
    ) -> int:
        def _op(conn) -> int:
            now = utc_now()
            cur = conn.execute(
                """
                UPDATE review_submissions
                SET status = 'published',
                    published_chat_id = ?,
                    published_message_id = ?,
                    reviewed_at = COALESCE(reviewed_at, ?),
                    published_at = ?
                WHERE bot_id = ? AND review_id = ?
                  AND status = 'pending' AND consent_to_publish = 1
                """,
                (published_chat_id, published_message_id, now, now, bot_id, review_id),
            )
            return int(cur.rowcount)

        return await self._engine.run(_op)

    async def mark_rejected(self, bot_id: str, review_id: str) -> int:
        def _op(conn) -> int:
            now = utc_now()
            cur = conn.execute(
                """
                UPDATE review_submissions
                SET status = 'rejected',
                    reviewed_at = ?
                WHERE bot_id = ? AND review_id = ? AND status = 'pending'
                """,
                (now, bot_id, review_id),
            )
            return int(cur.rowcount)

        return await self._engine.run(_op)
