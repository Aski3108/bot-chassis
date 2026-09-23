"""Подарочный доступ: замена активного ряда, ленивая проверка, отзыв."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from ..engine import StorageEngine, parse_utc, utc_now
from .users import UsersRepository

DEFAULT_PLAN_CODE = "default"


@dataclass(slots=True, frozen=True)
class SubscriptionRecord:
    id: int
    bot_id: str
    user_id: int
    plan_code: str
    is_lifetime: bool
    expires_at: Optional[str]
    granted_by: int
    grant_reason: Optional[str]
    status: str


def _row_to_sub(row) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=int(row["id"]),
        bot_id=row["bot_id"],
        user_id=int(row["user_id"]),
        plan_code=row["plan_code"],
        is_lifetime=bool(row["is_lifetime"]),
        expires_at=row["expires_at"],
        granted_by=int(row["granted_by"]),
        grant_reason=row["grant_reason"],
        status=row["status"],
    )


class SubscriptionsRepository:
    def __init__(self, engine: StorageEngine, users: UsersRepository) -> None:
        self._engine = engine
        self._users = users

    async def grant_gift_access(
        self,
        bot_id: str,
        user_id: int,
        granted_by: int,
        days: Optional[int] = None,
        plan_code: str = DEFAULT_PLAN_CODE,
        reason: str = "gift",
    ) -> tuple[bool, Optional[str]]:
        if days is not None and days < 0:
            return False, "invalid_days"
        plan = plan_code or DEFAULT_PLAN_CODE
        is_lifetime = days is None or days == 0
        expires_at = None
        if not is_lifetime:
            expires_at = (
                parse_utc(utc_now()) + timedelta(days=int(days))
            ).strftime("%Y-%m-%d %H:%M:%S")

        await self._users.upsert_user(bot_id, user_id)
        now = utc_now()

        def _op(conn) -> tuple[bool, Optional[str]]:
            conn.execute(
                """
                UPDATE subscriptions
                SET status = 'revoked', updated_at = ?
                WHERE bot_id = ? AND user_id = ? AND plan_code = ? AND status = 'active'
                """,
                (now, bot_id, user_id, plan),
            )
            conn.execute(
                """
                INSERT INTO subscriptions (
                    bot_id, user_id, plan_code, is_lifetime, expires_at,
                    granted_by, grant_reason, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    bot_id,
                    user_id,
                    plan,
                    1 if is_lifetime else 0,
                    expires_at,
                    granted_by,
                    reason,
                    now,
                ),
            )
            return True, None

        return await self._engine.run(_op)

    async def revoke_gift_access(
        self,
        bot_id: str,
        user_id: int,
        plan_code: str = DEFAULT_PLAN_CODE,
    ) -> tuple[bool, Optional[str]]:
        plan = plan_code or DEFAULT_PLAN_CODE
        now = utc_now()

        def _op(conn) -> tuple[bool, Optional[str]]:
            cur = conn.execute(
                """
                UPDATE subscriptions
                SET status = 'revoked', updated_at = ?
                WHERE bot_id = ? AND user_id = ? AND plan_code = ? AND status = 'active'
                """,
                (now, bot_id, user_id, plan),
            )
            if cur.rowcount == 0:
                return False, "not_found"
            return True, None

        return await self._engine.run(_op)

    async def has_active_access(
        self,
        bot_id: str,
        user_id: int,
        plan_code: str = DEFAULT_PLAN_CODE,
    ) -> bool:
        plan = plan_code or DEFAULT_PLAN_CODE
        now = parse_utc(utc_now())

        def _op(conn) -> bool:
            rows = conn.execute(
                """
                SELECT is_lifetime, expires_at FROM subscriptions
                WHERE bot_id = ? AND user_id = ? AND plan_code = ? AND status = 'active'
                """,
                (bot_id, user_id, plan),
            ).fetchall()
            for row in rows:
                if int(row["is_lifetime"]) == 1:
                    return True
                expires_at = row["expires_at"]
                if expires_at and parse_utc(expires_at) > now:
                    return True
            return False

        return await self._engine.run(_op)

    async def get_active_subscription(
        self,
        bot_id: str,
        user_id: int,
        plan_code: str = DEFAULT_PLAN_CODE,
    ) -> Optional[SubscriptionRecord]:
        plan = plan_code or DEFAULT_PLAN_CODE

        def _op(conn) -> Optional[SubscriptionRecord]:
            row = conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE bot_id = ? AND user_id = ? AND plan_code = ? AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
                """,
                (bot_id, user_id, plan),
            ).fetchone()
            return _row_to_sub(row) if row else None

        record = await self._engine.run(_op)
        if record is None:
            return None
        if not await self.has_active_access(bot_id, user_id, plan):
            return None
        return record
