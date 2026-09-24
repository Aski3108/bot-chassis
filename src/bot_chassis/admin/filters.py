"""Фильтры /admin: admin или superadmin, и отдельно только superadmin."""

from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import TelegramObject

from ..storage.repositories.roles import RolesRepository


class AdminRoleFilter(Filter):
    """Пропускает admin и superadmin этого bot_id."""

    def __init__(self, bot_id: str, roles: RolesRepository) -> None:
        self.bot_id = bot_id
        self.roles = roles

    async def __call__(self, event: TelegramObject) -> bool:
        user_id = _user_id(event)
        if user_id is None:
            return False
        return await self.roles.has_any_role(self.bot_id, user_id, ("admin", "superadmin"))


class SuperadminRoleFilter(Filter):
    """Пропускает только superadmin этого bot_id."""

    def __init__(self, bot_id: str, roles: RolesRepository) -> None:
        self.bot_id = bot_id
        self.roles = roles

    async def __call__(self, event: TelegramObject) -> bool:
        user_id = _user_id(event)
        if user_id is None:
            return False
        return await self.roles.has_any_role(self.bot_id, user_id, ("superadmin",))


def _user_id(event: TelegramObject) -> int | None:
    user = getattr(event, "from_user", None)
    if user is None:
        inner = getattr(event, "event", None)
        if inner is not None:
            user = getattr(inner, "from_user", None)
    if user is not None and getattr(user, "id", None) is not None:
        return int(user.id)
    return None
