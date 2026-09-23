"""Гейт задач кузова: рубильник, тень, обычный бан. Платежи сюда не ходят."""

from __future__ import annotations

from typing import Protocol

from ..storage.repositories.bot_settings import BotSettingsRepository
from ..storage.repositories.users import UsersRepository


class WorkGatePort(Protocol):
    async def can_accept_work(self, bot_id: str, user_id: int) -> tuple[bool, str | None]: ...


class DefaultWorkGateAdapter(WorkGatePort):
    def __init__(self, settings_repo: BotSettingsRepository, users_repo: UsersRepository):
        self._settings = settings_repo
        self._users = users_repo

    async def can_accept_work(self, bot_id: str, user_id: int) -> tuple[bool, str | None]:
        is_maint, reason = await self._settings.get_maintenance_status(bot_id)
        if is_maint:
            return False, reason or "Сервис временно приостановлен."
        user = await self._users.get_user(bot_id, user_id)
        if user:
            if user.is_shadow_banned:
                return False, None
            if user.is_banned:
                return False, user.ban_reason or "Доступ к сервису ограничен."
        return True, None
