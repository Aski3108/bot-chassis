"""Доступ и подарки: тонкая трансляция в SubscriptionsRepository."""

from __future__ import annotations

from typing import Protocol

from ..storage.repositories.subscriptions import SubscriptionsRepository


class AccessPort(Protocol):
    async def has_active_access(self, bot_id: str, user_id: int, plan_code: str = "default") -> bool: ...

    async def grant_gift_access(
        self,
        bot_id: str,
        user_id: int,
        granted_by: int,
        days: int | None = None,
        plan_code: str = "default",
        reason: str = "gift",
    ) -> tuple[bool, str | None]: ...

    async def revoke_gift_access(
        self,
        bot_id: str,
        user_id: int,
        plan_code: str = "default",
    ) -> tuple[bool, str | None]: ...


class DefaultAccessAdapter(AccessPort):
    def __init__(self, subs_repo: SubscriptionsRepository):
        self._subs = subs_repo

    async def has_active_access(self, bot_id: str, user_id: int, plan_code: str = "default") -> bool:
        return await self._subs.has_active_access(bot_id, user_id, plan_code=plan_code)

    async def grant_gift_access(
        self,
        bot_id: str,
        user_id: int,
        granted_by: int,
        days: int | None = None,
        plan_code: str = "default",
        reason: str = "gift",
    ) -> tuple[bool, str | None]:
        return await self._subs.grant_gift_access(
            bot_id,
            user_id,
            granted_by=granted_by,
            days=days,
            plan_code=plan_code,
            reason=reason,
        )

    async def revoke_gift_access(
        self,
        bot_id: str,
        user_id: int,
        plan_code: str = "default",
    ) -> tuple[bool, str | None]:
        return await self._subs.revoke_gift_access(bot_id, user_id, plan_code=plan_code)
