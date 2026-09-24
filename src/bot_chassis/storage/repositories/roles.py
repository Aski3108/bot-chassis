"""Роли admin/superadmin: посев, выдача, атомарный отзыв последнего суперадмина."""

from __future__ import annotations

from typing import Optional, Sequence

from loguru import logger

from ..engine import StorageEngine
from .users import UsersRepository

ALLOWED_ROLES = frozenset({"admin", "superadmin"})


class RolesRepository:
    def __init__(self, engine: StorageEngine, users: UsersRepository) -> None:
        self._engine = engine
        self._users = users

    async def seed_superadmins(self, bot_id: str, superadmin_ids: Sequence[int]) -> int:
        ids = tuple(int(uid) for uid in superadmin_ids)
        if not ids:
            count = await self.count_role(bot_id, "superadmin")
            if count == 0:
                logger.warning(
                    "CHASSIS_SUPERADMIN_IDS пуст и в базе нет суперадминов "
                    f"(bot_id={bot_id!r}). /admin будет недоступен, пока роль не выдадут."
                )
            return 0

        seeded = 0
        for user_id in ids:
            await self._users.upsert_user(bot_id, user_id)
            created = await self._insert_role(bot_id, user_id, "superadmin", granted_by=None)
            if created:
                seeded += 1
        return seeded

    async def count_role(self, bot_id: str, role: str) -> int:
        def _op(conn) -> int:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM roles WHERE bot_id = ? AND role = ?",
                (bot_id, role),
            ).fetchone()
            return int(row["n"])

        return await self._engine.run(_op)

    async def has_any_role(self, bot_id: str, user_id: int, roles: Sequence[str]) -> bool:
        wanted = tuple(roles)
        if not wanted:
            return False

        def _op(conn) -> bool:
            placeholders = ",".join("?" * len(wanted))
            row = conn.execute(
                f"""
                SELECT 1 FROM roles
                WHERE bot_id = ? AND user_id = ? AND role IN ({placeholders})
                LIMIT 1
                """,
                (bot_id, user_id, *wanted),
            ).fetchone()
            return row is not None

        return await self._engine.run(_op)

    async def grant_role(
        self,
        bot_id: str,
        user_id: int,
        role: str,
        granted_by: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        if role not in ALLOWED_ROLES:
            return False, "invalid_role"
        await self._users.upsert_user(bot_id, user_id)
        created = await self._insert_role(bot_id, user_id, role, granted_by)
        if not created:
            return False, "already_granted"
        return True, None

    async def revoke_role(
        self,
        bot_id: str,
        user_id: int,
        role: str,
    ) -> tuple[bool, Optional[str]]:
        if role not in ALLOWED_ROLES:
            return False, "invalid_role"

        def _op(conn) -> tuple[bool, Optional[str]]:
            if role == "superadmin":
                cur = conn.execute(
                    """
                    DELETE FROM roles
                    WHERE rowid IN (
                        SELECT r.rowid FROM roles r
                        JOIN users u ON u.bot_id = r.bot_id AND u.user_id = r.user_id
                        WHERE r.bot_id = ? AND r.user_id = ? AND r.role = 'superadmin'
                          AND (
                            u.is_banned = 1
                            OR (
                              SELECT COUNT(*) FROM roles r2
                              JOIN users u2 ON u2.bot_id = r2.bot_id AND u2.user_id = r2.user_id
                              WHERE r2.bot_id = r.bot_id
                                AND r2.role = 'superadmin'
                                AND u2.is_banned = 0
                            ) > 1
                          )
                    )
                    """,
                    (bot_id, user_id),
                )
                if cur.rowcount > 0:
                    return True, None
                still = conn.execute(
                    """
                    SELECT 1 FROM roles
                    WHERE bot_id = ? AND user_id = ? AND role = 'superadmin'
                    """,
                    (bot_id, user_id),
                ).fetchone()
                if still:
                    return False, "last_superadmin"
                return False, "not_found"

            cur = conn.execute(
                "DELETE FROM roles WHERE bot_id = ? AND user_id = ? AND role = ?",
                (bot_id, user_id, role),
            )
            if cur.rowcount == 0:
                return False, "not_found"
            return True, None

        return await self._engine.run(_op)

    async def _insert_role(
        self,
        bot_id: str,
        user_id: int,
        role: str,
        granted_by: Optional[int],
    ) -> bool:
        def _op(conn) -> bool:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO roles (bot_id, user_id, role, granted_by)
                VALUES (?, ?, ?, ?)
                """,
                (bot_id, user_id, role, granted_by),
            )
            return cur.rowcount > 0

        return await self._engine.run(_op)
