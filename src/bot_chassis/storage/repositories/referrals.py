"""Реферальные связи: одна запись на приглашённого, без бонусной логики шасси."""

from __future__ import annotations

from typing import Optional

from ..engine import StorageEngine, utc_now
from .users import UsersRepository


class ReferralsRepository:
    def __init__(self, engine: StorageEngine, users: UsersRepository) -> None:
        self._engine = engine
        self._users = users

    async def record_referral(
        self,
        bot_id: str,
        referrer_id: int,
        referee_id: int,
    ) -> tuple[bool, Optional[str]]:
        if referrer_id == referee_id:
            return False, "self_referral"
        await self._users.upsert_user(bot_id, referrer_id)
        await self._users.upsert_user(bot_id, referee_id)

        def _op(conn) -> tuple[bool, Optional[str]]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO referrals (
                    bot_id, referrer_id, referee_id, rewarded, created_at
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (bot_id, referrer_id, referee_id, utc_now()),
            )
            if cur.rowcount > 0:
                return True, None
            return False, "already_exists"

        return await self._engine.run(_op)

    async def get_referrals_count(self, bot_id: str, referrer_id: int) -> int:
        def _op(conn) -> int:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM referrals
                WHERE bot_id = ? AND referrer_id = ?
                """,
                (bot_id, referrer_id),
            ).fetchone()
            return int(row["n"])

        return await self._engine.run(_op)

    async def mark_referral_rewarded(self, bot_id: str, referee_id: int) -> bool:
        def _op(conn) -> bool:
            cur = conn.execute(
                """
                UPDATE referrals
                SET rewarded = 1
                WHERE bot_id = ? AND referee_id = ?
                """,
                (bot_id, referee_id),
            )
            return cur.rowcount > 0

        return await self._engine.run(_op)
