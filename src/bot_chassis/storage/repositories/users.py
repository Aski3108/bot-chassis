"""Пользователи: upsert без затирания языка, бан, тень, first-touch трафик."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine import StorageEngine, utc_now

_KEEP = object()


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
    telegram_language_code: Optional[str] = None
    locale_source: str = "legacy"


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
        telegram_language_code=row["telegram_language_code"] if "telegram_language_code" in row.keys() else None,
        locale_source=row["locale_source"] if "locale_source" in row.keys() else "legacy",
    )


class UsersRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def upsert_user(
        self,
        bot_id: str,
        user_id: int,
        username: Optional[str] | object = _KEEP,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> UserRecord:
        def _op(conn) -> UserRecord:
            keep_username = username is _KEEP
            stored_username = None if keep_username else normalize_username(
                username if isinstance(username, str) else None
            )
            if not keep_username and stored_username is not None:
                _release_username(conn, bot_id, user_id, stored_username)
            username_update = (
                "username = COALESCE(excluded.username, users.username)"
                if keep_username
                else "username = excluded.username"
            )
            conn.execute(
                f"""
                INSERT INTO users (
                    bot_id, user_id, username, first_name, last_name, language_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, user_id) DO UPDATE SET
                    {username_update},
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_name = COALESCE(excluded.last_name, users.last_name),
                    language_code = users.language_code,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id,
                    user_id,
                    stored_username,
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

    async def set_manual_locale(self, bot_id: str, user_id: int, language_code: str) -> bool:
        """Ручной выбор. Дальше автоматика не меняет language_code."""

        def _op(conn) -> bool:
            cur = conn.execute(
                """
                UPDATE users
                SET language_code = ?, locale_source = 'manual', updated_at = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (language_code, utc_now(), bot_id, user_id),
            )
            return cur.rowcount > 0

        return await self._engine.run(_op)

    async def record_telegram_visit(
        self,
        bot_id: str,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        telegram_language_code: Optional[str],
        resolved_locale: str,
    ) -> UserRecord:
        """Первый визит записывает вычисленную локаль. Повтор только обновляет сырой код."""

        def _op(conn) -> UserRecord:
            stored_username = normalize_username(username)
            if stored_username is not None:
                _release_username(conn, bot_id, user_id, stored_username)
            conn.execute(
                """
                INSERT INTO users (
                    bot_id, user_id, username, first_name, last_name,
                    language_code, telegram_language_code, locale_source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'auto', ?)
                ON CONFLICT(bot_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_name = COALESCE(excluded.last_name, users.last_name),
                    telegram_language_code = excluded.telegram_language_code,
                    language_code = users.language_code,
                    locale_source = users.locale_source,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id,
                    user_id,
                    stored_username,
                    first_name,
                    last_name,
                    resolved_locale,
                    telegram_language_code,
                    utc_now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE bot_id = ? AND user_id = ?",
                (bot_id, user_id),
            ).fetchone()
            return _row_to_user(row)

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

    async def get_broadcast_user_ids(self, bot_id: str, telegram_bot_id: int | None = None) -> list[int]:
        """Без telegram_bot_id — прежний список. С ним пропускаются stopped и deleted этого бота."""

        def _op(conn) -> list[int]:
            if telegram_bot_id is None:
                rows = conn.execute(
                    """
                    SELECT user_id FROM users
                    WHERE bot_id = ? AND is_banned = 0 AND is_shadow_banned = 0
                    ORDER BY user_id ASC
                    """,
                    (bot_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT user_id FROM users AS u
                    WHERE u.bot_id = ? AND u.is_banned = 0 AND u.is_shadow_banned = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM user_bot_statuses AS s
                          WHERE s.bot_id = u.bot_id
                            AND s.user_id = u.user_id
                            AND s.telegram_bot_id = ?
                            AND s.status IN ('stopped', 'deleted')
                      )
                    ORDER BY u.user_id ASC
                    """,
                    (bot_id, telegram_bot_id),
                ).fetchall()
            return [int(row["user_id"]) for row in rows]

        return await self._engine.run(_op)

    async def find_by_username(self, bot_id: str, username: str) -> list[UserRecord]:
        """Регистронезависимый поиск ника без @. Несколько старых строк не схлопываются."""
        normalized = normalize_username(username)
        if not normalized:
            return []

        def _op(conn) -> list[UserRecord]:
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE bot_id = ? AND username = ? COLLATE NOCASE
                ORDER BY user_id ASC
                """,
                (bot_id, normalized),
            ).fetchall()
            return [_row_to_user(row) for row in rows]

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


def normalize_username(value: str | None) -> str | None:
    """Храним и ищем ник без @. Пустая строка — отсутствия ника."""
    if value is None:
        return None
    text = value.strip()
    if text.startswith("@"):
        text = text[1:].strip()
    return text or None


def _release_username(conn, bot_id: str, user_id: int, username: str) -> None:
    conn.execute(
        """
        UPDATE users
        SET username = NULL, updated_at = ?
        WHERE bot_id = ? AND user_id != ? AND username = ? COLLATE NOCASE
        """,
        (utc_now(), bot_id, user_id, username),
    )


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
