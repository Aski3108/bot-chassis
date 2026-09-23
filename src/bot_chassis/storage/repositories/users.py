"""Пользователи: upsert без затирания языка, бан, тень, first-touch трафик."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine import StorageEngine, utc_now


@dataclass(slots=True, frozen=True)
class UserRecord:
    bot_id: str
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    language_code: str
    is_banned: bool
    ban_reason: Optional[str]
    consent_at: Optional[str]
    created_at: str
    traffic_source: Optional[str] = None
    is_shadow_banned: bool = False


def _row_to_user(row) -> UserRecord:
    return UserRecord(
        bot_id=row["bot_id"],
        user_id=int(row["user_id"]),
        username=row["username"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        language_code=row["language_code"],
        is_banned=bool(row["is_banned"]),
        ban_reason=row["ban_reason"],
        consent_at=row["consent_at"],
        created_at=row["created_at"],
        traffic_source=row["traffic_source"],
        is_shadow_banned=bool(row["is_shadow_banned"]),
    )


class UsersRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def upsert_user(
        self,
        bot_id: str,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> UserRecord:
        def _op(conn) -> UserRecord:
            conn.execute(
                """
                INSERT INTO users (
                    bot_id, user_id, username, first_name, last_name, language_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_name = COALESCE(excluded.last_name, users.last_name),
                    language_code = users.language_code,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id,
                    user_id,
                    username,
                    first_name,
                    last_name,
                    language_code or "ru",
                    utc_now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE bot_id = ? AND user_id = ?",
                (bot_id, user_id),
            ).fetchone()
            return _row_to_user(row)

        return await self._engine.run(_op)

    async def set_language_code(self, bot_id: str, user_id: int, language_code: str) -> bool:
        def _op(conn) -> bool:
            cur = conn.execute(
                """
                UPDATE users
                SET language_code = ?, updated_at = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (language_code, utc_now(), bot_id, user_id),
            )
            return cur.rowcount > 0

        return await self._engine.run(_op)

    async def set_traffic_source(self, bot_id: str, user_id: int, traffic_source: str) -> bool:
        """First-touch: write only while the column is empty. True if the user exists."""

        def _op(conn) -> bool:
            conn.execute(
                """
                UPDATE users
                SET traffic_source = ?, updated_at = ?
                WHERE bot_id = ? AND user_id = ?
                  AND (traffic_source IS NULL OR traffic_source = '')
                """,
                (traffic_source, utc_now(), bot_id, user_id),
            )
            exists = conn.execute(
                "SELECT 1 FROM users WHERE bot_id = ? AND user_id = ?",
                (bot_id, user_id),
            ).fetchone()
            return exists is not None

        return await self._engine.run(_op)

    async def set_shadow_ban(
        self,
        bot_id: str,
        user_id: int,
        is_shadow_banned: bool,
    ) -> tuple[bool, Optional[str]]:
        def _op(conn) -> tuple[bool, Optional[str]]:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE bot_id = ? AND user_id = ?",
                (bot_id, user_id),
            ).fetchone()
            if not exists:
                return False, "not_found"
            if is_shadow_banned and _has_staff_role(conn, bot_id, user_id):
                return False, "target_is_admin"
            conn.execute(
                """
                UPDATE users
                SET is_shadow_banned = ?, updated_at = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (1 if is_shadow_banned else 0, utc_now(), bot_id, user_id),
            )
            return True, None

        return await self._engine.run(_op)

    async def get_broadcast_user_ids(self, bot_id: str) -> list[int]:
        def _op(conn) -> list[int]:
            rows = conn.execute(
                """
                SELECT user_id FROM users
                WHERE bot_id = ? AND is_banned = 0 AND is_shadow_banned = 0
                ORDER BY user_id ASC
                """,
                (bot_id,),
            ).fetchall()
            return [int(row["user_id"]) for row in rows]

        return await self._engine.run(_op)

    async def get_user(self, bot_id: str, user_id: int) -> Optional[UserRecord]:
        def _op(conn) -> Optional[UserRecord]:
            row = conn.execute(
                "SELECT * FROM users WHERE bot_id = ? AND user_id = ?",
                (bot_id, user_id),
            ).fetchone()
            return _row_to_user(row) if row else None

        return await self._engine.run(_op)

    async def set_consent(
        self,
        bot_id: str,
        user_id: int,
        consent_at: Optional[str],
    ) -> bool:
        def _op(conn) -> bool:
            cur = conn.execute(
                """
                UPDATE users
                SET consent_at = ?, updated_at = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (consent_at, utc_now(), bot_id, user_id),
            )
            return cur.rowcount > 0

        return await self._engine.run(_op)

    async def get_consent(self, bot_id: str, user_id: int) -> Optional[str]:
        user = await self.get_user(bot_id, user_id)
        return user.consent_at if user else None

    async def set_ban(
        self,
        bot_id: str,
        user_id: int,
        is_banned: bool,
        reason: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        def _op(conn) -> tuple[bool, Optional[str]]:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE bot_id = ? AND user_id = ?",
                (bot_id, user_id),
            ).fetchone()
            if not exists:
                return False, "not_found"
            if is_banned and _is_last_unbanned_superadmin(conn, bot_id, user_id):
                return False, "last_superadmin"
            conn.execute(
                """
                UPDATE users
                SET is_banned = ?, ban_reason = ?, updated_at = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (1 if is_banned else 0, reason if is_banned else None, utc_now(), bot_id, user_id),
            )
            return True, None

        return await self._engine.run(_op)


def _has_staff_role(conn, bot_id: str, user_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM roles
        WHERE bot_id = ? AND user_id = ? AND role IN ('admin', 'superadmin')
        LIMIT 1
        """,
        (bot_id, user_id),
    ).fetchone()
    return row is not None


def _is_last_unbanned_superadmin(conn, bot_id: str, user_id: int) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM roles r
        JOIN users u ON u.bot_id = r.bot_id AND u.user_id = r.user_id
        WHERE r.bot_id = ? AND r.role = 'superadmin' AND u.is_banned = 0
        """,
        (bot_id,),
    ).fetchone()
    if int(row["n"]) != 1:
        return False
    target = conn.execute(
        """
        SELECT 1
        FROM roles r
        JOIN users u ON u.bot_id = r.bot_id AND u.user_id = r.user_id
        WHERE r.bot_id = ? AND r.user_id = ? AND r.role = 'superadmin' AND u.is_banned = 0
        """,
        (bot_id, user_id),
    ).fetchone()
    return target is not None
