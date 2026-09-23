"""Рефералка: запись связи и счётчик. Бонус кузов ставит сам."""

from __future__ import annotations

from typing import Protocol

from ..storage.repositories.referrals import ReferralsRepository


class ReferralPort(Protocol):
    async def record_referral(
        self,
        bot_id: str,
        referrer_id: int,
        referee_id: int,
    ) -> tuple[bool, str | None]: ...

    async def get_referrals_count(self, bot_id: str, referrer_id: int) -> int: ...

    async def mark_referral_rewarded(self, bot_id: str, referee_id: int) -> bool: ...


class DefaultReferralAdapter(ReferralPort):
    def __init__(self, referrals_repo: ReferralsRepository):
        self._referrals = referrals_repo

    async def record_referral(
        self,
        bot_id: str,
        referrer_id: int,
        referee_id: int,
    ) -> tuple[bool, str | None]:
        return await self._referrals.record_referral(bot_id, referrer_id, referee_id)

    async def get_referrals_count(self, bot_id: str, referrer_id: int) -> int:
        return await self._referrals.get_referrals_count(bot_id, referrer_id)

    async def mark_referral_rewarded(self, bot_id: str, referee_id: int) -> bool:
        return await self._referrals.mark_referral_rewarded(bot_id, referee_id)
