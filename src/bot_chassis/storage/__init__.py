"""Контур хранения полной рамы (SQLite, обязательный bot_id)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import BotChassisConfig

from .engine import StorageEngine, utc_now
from .repositories.bot_settings import BotSettingsRepository
from .repositories.referrals import ReferralsRepository
from .repositories.roles import RolesRepository
from .repositories.subscriptions import SubscriptionsRepository
from .repositories.support_threads import SupportThreadsRepository
from .repositories.transactions import TransactionsRepository, VoucherRecord
from .repositories.users import UserRecord, UsersRepository


@dataclass(slots=True)
class Storage:
    engine: StorageEngine
    users: UsersRepository
    roles: RolesRepository
    transactions: TransactionsRepository
    subscriptions: SubscriptionsRepository
    support_threads: SupportThreadsRepository
    bot_settings: BotSettingsRepository
    referrals: ReferralsRepository


async def create_storage(config: BotChassisConfig) -> Storage:
    engine = StorageEngine(config.db_path)
    await engine.initialize()
    users = UsersRepository(engine)
    roles = RolesRepository(engine, users)
    storage = Storage(
        engine=engine,
        users=users,
        roles=roles,
        transactions=TransactionsRepository(engine),
        subscriptions=SubscriptionsRepository(engine, users),
        support_threads=SupportThreadsRepository(engine),
        bot_settings=BotSettingsRepository(engine),
        referrals=ReferralsRepository(engine, users),
    )
    await roles.seed_superadmins(config.bot_id, config.superadmin_ids)
    return storage


__all__ = [
    "Storage",
    "StorageEngine",
    "UserRecord",
    "VoucherRecord",
    "create_storage",
    "utc_now",
]
