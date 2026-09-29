"""Контур хранения полной рамы (SQLite, обязательный bot_id)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import BotChassisConfig

from .engine import StorageEngine, utc_now
from .repositories.bot_settings import BotSettingsRepository
from .repositories.chassis_events import ChassisEventsRepository
from .repositories.referrals import ReferralsRepository
from .repositories.reviews import ReviewRecord, ReviewSubmissionsRepository
from .repositories.roles import RolesRepository
from .repositories.subscriptions import SubscriptionsRepository
from .repositories.support_threads import SupportThreadsRepository
from .repositories.transactions import TransactionsRepository, VoucherRecord
from .repositories.scheduled_jobs import ScheduledJobRunsRepository
from .repositories.user_bot_statuses import UserBotStatusRepository
from .repositories.users import UserRecord, UsersRepository


@dataclass(slots=True)
class Storage:
    engine: StorageEngine
    users: UsersRepository
    roles: RolesRepository
    transactions: TransactionsRepository
    subscriptions: SubscriptionsRepository
    support_threads: SupportThreadsRepository
    reviews: ReviewSubmissionsRepository
    bot_settings: BotSettingsRepository
    referrals: ReferralsRepository
    bot_statuses: UserBotStatusRepository
    scheduled_jobs: ScheduledJobRunsRepository
    events: ChassisEventsRepository


async def create_storage(config: BotChassisConfig) -> Storage:
    engine = StorageEngine(config.db_path)
    await engine.initialize()
    users = UsersRepository(engine)
    roles = RolesRepository(engine, users)
    bot_statuses = UserBotStatusRepository(engine)
    storage = Storage(
        engine=engine,
        users=users,
        roles=roles,
        transactions=TransactionsRepository(engine),
        subscriptions=SubscriptionsRepository(engine, users),
        support_threads=SupportThreadsRepository(engine),
        reviews=ReviewSubmissionsRepository(engine),
        bot_settings=BotSettingsRepository(engine),
        referrals=ReferralsRepository(engine, users),
        bot_statuses=bot_statuses,
        scheduled_jobs=ScheduledJobRunsRepository(engine),
        events=ChassisEventsRepository(engine),
    )
    await roles.seed_superadmins(config.bot_id, config.superadmin_ids)
    return storage


__all__ = [
    "ReviewRecord",
    "Storage",
    "StorageEngine",
    "UserRecord",
    "VoucherRecord",
    "create_storage",
    "utc_now",
]
