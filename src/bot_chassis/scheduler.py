"""Единый планировщик рамы: lifecycle диспетчера и DB-claim."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from loguru import logger

from .config import BotChassisConfig
from .policies import BACKUP_JOB_KEY, REPORT_JOB_KEY, BackupPolicy, ReportingPolicy
from .reports import (
    as_utc_stamp,
    collect_chassis_aggregates,
    daily_period_start,
    format_chassis_report,
    is_month_end,
    is_sunday,
    month_bounds_utc,
    week_bounds_utc,
)
from .service_notify import deliver_service_message, resolve_service_destination
from .storage import Storage
from .storage.backup import BackupError, SnapshotResult, create_nightly_archive


def due_slot_utc(now: datetime, policy: BackupPolicy | ReportingPolicy) -> datetime:
    """Последний наступивший слот hour:minute в поясе политики, как aware UTC."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(policy.tz)
    slot = local.replace(hour=policy.hour, minute=policy.minute, second=0, microsecond=0)
    if local < slot:
        slot -= timedelta(days=1)
    return slot.astimezone(timezone.utc)


def next_slot_utc(now: datetime, policy: BackupPolicy | ReportingPolicy) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(policy.tz)
    slot = local.replace(hour=policy.hour, minute=policy.minute, second=0, microsecond=0)
    if local >= slot:
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc)


def slot_key(slot_utc: datetime) -> str:
    aware = slot_utc if slot_utc.tzinfo else slot_utc.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class BackupScheduler:
    def __init__(
        self,
        *,
        bot,
        config: BotChassisConfig,
        storage: Storage,
        policy: BackupPolicy,
        origin_bot_id: str,
        telegram_bot_id: int,
    ) -> None:
        self._bot = bot
        self._config = config
        self._storage = storage
        self._policy = policy
        self._origin = origin_bot_id
        self._telegram_bot_id = telegram_bot_id
        self._claim_owner = f"{origin_bot_id}|{telegram_bot_id}|{uuid.uuid4().hex}"
        self._stop = asyncio.Event()

    @property
    def claimed_by(self) -> str:
        return f"{self._origin}|{self._telegram_bot_id}"

    def owns_loop(self) -> bool:
        owner = self._policy.scheduler_owner_origin_bot_id
        return owner is None or owner == self._origin

    async def run_due(self, now: datetime | None = None) -> SnapshotResult | None:
        if not self.owns_loop():
            return None
        moment = now or datetime.now(timezone.utc)
        slot = due_slot_utc(moment, self._policy)
        if moment.astimezone(timezone.utc) < slot:
            return None
        scheduled_for = slot_key(slot)
        won = await self._storage.scheduled_jobs.claim(
            self._config.bot_id,
            BACKUP_JOB_KEY,
            scheduled_for,
            self._claim_owner,
            stale_after_seconds=self._policy.claim_stale_after_seconds,
        )
        if not won:
            return None
        await self._storage.scheduled_jobs.mark_status(
            self._config.bot_id,
            BACKUP_JOB_KEY,
            scheduled_for,
            "running",
            expected_claimed_by=self._claim_owner,
        )
        local_when = slot.astimezone(self._policy.tz)
        try:
            result = await create_nightly_archive(self._storage.engine, self._policy, local_when)
        except Exception as exc:
            logger.exception("Ночной бэкап не удался")
            await self._storage.scheduled_jobs.mark_status(
                self._config.bot_id,
                BACKUP_JOB_KEY,
                scheduled_for,
                "failed",
                details=str(exc)[:500],
                complete=True,
                expected_claimed_by=self._claim_owner,
            )
            await self._notify_ops(f"Backup failed. slot={scheduled_for} by={self.claimed_by}: {exc}")
            if not isinstance(exc, BackupError):
                raise
            return None
        await self._storage.scheduled_jobs.mark_status(
            self._config.bot_id,
            BACKUP_JOB_KEY,
            scheduled_for,
            "done",
            details=result.path.name,
            complete=True,
            expected_claimed_by=self._claim_owner,
        )
        await self._notify_ops(
            f"Backup ok. {result.kind} {result.path.name} bytes={result.bytes} by={self.claimed_by}"
        )
        return result

    async def loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Сбой цикла бэкапа")
            delay = max(1.0, (next_slot_utc(datetime.now(timezone.utc), self._policy) - datetime.now(timezone.utc)).total_seconds())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=min(delay, 3600.0))
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def _notify_ops(self, text: str) -> None:
        destination = resolve_service_destination(self._config, "ops")
        try:
            await deliver_service_message(self._bot, destination, text)
        except Exception:
            logger.exception("Не удалось отправить итог бэкапа в ops")


def register_backup_scheduler(dp, scheduler: BackupScheduler) -> None:
    """Подключает цикл к startup/shutdown. Не стартует при импорте модуля."""

    async def _start(_dispatcher=None) -> None:
        if not scheduler.owns_loop():
            return
        existing = dp.workflow_data.get("chassis_backup_task")
        if existing is not None and not existing.done():
            return
        dp.workflow_data["chassis_backup_scheduler"] = scheduler
        dp.workflow_data["chassis_backup_task"] = asyncio.create_task(scheduler.loop())

    async def _stop(_dispatcher=None) -> None:
        scheduler.stop()
        task = dp.workflow_data.pop("chassis_backup_task", None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    dp.startup.register(_start)
    dp.shutdown.register(_stop)


class ReportScheduler:
    def __init__(
        self,
        *,
        bot,
        config: BotChassisConfig,
        storage: Storage,
        policy: ReportingPolicy,
        origin_bot_id: str,
        telegram_bot_id: int,
        donation_sku_codes: tuple[str, ...] = (),
    ) -> None:
        self._bot = bot
        self._config = config
        self._storage = storage
        self._policy = policy
        self._origin = origin_bot_id
        self._telegram_bot_id = telegram_bot_id
        self._donation_sku_codes = donation_sku_codes
        self._claim_owner = f"{origin_bot_id}|{telegram_bot_id}|{uuid.uuid4().hex}"
        self._stop = asyncio.Event()

    @property
    def claimed_by(self) -> str:
        return f"{self._origin}|{self._telegram_bot_id}"

    def owns_loop(self) -> bool:
        owner = self._policy.scheduler_owner_origin_bot_id
        return owner is None or owner == self._origin

    async def run_due(self, now: datetime | None = None) -> str | None:
        if not self.owns_loop():
            return None
        moment = now or datetime.now(timezone.utc)
        slot = due_slot_utc(moment, self._policy)
        if moment.astimezone(timezone.utc) < slot:
            return None
        previous = await self._storage.scheduled_jobs.latest_done(
            self._config.bot_id,
            REPORT_JOB_KEY,
        )
        first_run = await self._storage.scheduled_jobs.earliest(
            self._config.bot_id,
            REPORT_JOB_KEY,
        )
        if previous is None and first_run is None:
            local_now = moment.astimezone(self._policy.tz)
            local_slot = slot.astimezone(self._policy.tz)
            started = self._policy.reporting_started_at
            if local_slot.date() < local_now.date():
                return None
            if started is not None:
                started_utc = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
                if started_utc.astimezone(timezone.utc) >= slot:
                    return None
        scheduled_for = slot_key(slot)
        won = await self._storage.scheduled_jobs.claim(
            self._config.bot_id,
            REPORT_JOB_KEY,
            scheduled_for,
            self._claim_owner,
            stale_after_seconds=self._policy.claim_stale_after_seconds,
        )
        if not won:
            return None
        await self._storage.scheduled_jobs.mark_status(
            self._config.bot_id,
            REPORT_JOB_KEY,
            scheduled_for,
            "running",
            expected_claimed_by=self._claim_owner,
        )
        try:
            previous_key = previous["scheduled_for"] if previous else None
            first_key = first_run["scheduled_for"] if first_run else None
            period_start = daily_period_start(
                slot,
                self._policy,
                previous_key,
                first_key,
            )
            daily = await collect_chassis_aggregates(
                self._storage,
                self._config.bot_id,
                period_start,
                slot,
                donation_sku_codes=self._donation_sku_codes,
            )
            weekly = None
            monthly = None
            if is_sunday(slot, self._policy):
                week_start, week_end = week_bounds_utc(slot, self._policy)
                weekly = await collect_chassis_aggregates(
                    self._storage,
                    self._config.bot_id,
                    week_start,
                    week_end,
                    donation_sku_codes=self._donation_sku_codes,
                )
            if is_month_end(slot, self._policy):
                month_start, month_end = month_bounds_utc(slot, self._policy)
                monthly = await collect_chassis_aggregates(
                    self._storage,
                    self._config.bot_id,
                    month_start,
                    month_end,
                    donation_sku_codes=self._donation_sku_codes,
                )
            text = format_chassis_report(
                daily,
                self._policy,
                weekly=weekly,
                monthly=monthly,
                slot_utc=slot,
            )
        except Exception as exc:
            logger.exception("Вечерний отчёт не собран")
            await self._storage.scheduled_jobs.mark_status(
                self._config.bot_id,
                REPORT_JOB_KEY,
                scheduled_for,
                "failed",
                details=str(exc)[:500],
                complete=True,
                expected_claimed_by=self._claim_owner,
            )
            await self._notify_ops(f"Report failed. slot={scheduled_for} by={self.claimed_by}: {exc}")
            raise
        delivered = await self._deliver(text, scheduled_for)
        if not delivered:
            await self._storage.scheduled_jobs.mark_status(
                self._config.bot_id,
                REPORT_JOB_KEY,
                scheduled_for,
                "failed",
                details="delivery",
                complete=True,
                expected_claimed_by=self._claim_owner,
            )
            return None
        await self._storage.scheduled_jobs.mark_status(
            self._config.bot_id,
            REPORT_JOB_KEY,
            scheduled_for,
            "done",
            details=f"{as_utc_stamp(period_start)}..{as_utc_stamp(slot)}",
            complete=True,
            expected_claimed_by=self._claim_owner,
        )
        return text

    async def loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Сбой цикла отчётов")
            delay = max(
                1.0,
                (next_slot_utc(datetime.now(timezone.utc), self._policy) - datetime.now(timezone.utc)).total_seconds(),
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=min(delay, 3600.0))
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def _deliver(self, text: str, scheduled_for: str) -> bool:
        events = resolve_service_destination(self._config, "events")
        if events is not None:
            try:
                await deliver_service_message(self._bot, events, text)
                return True
            except Exception as exc:
                logger.exception("Не удалось отправить отчёт в events")
                await self._notify_ops(f"Report delivery failed. slot={scheduled_for} by={self.claimed_by}: {exc}")
                return False
        ops = resolve_service_destination(self._config, "ops")
        if ops is None:
            logger.error("Нет events/ops для отчёта рамы")
            return False
        try:
            await deliver_service_message(self._bot, ops, text)
            return True
        except Exception as exc:
            logger.exception("Не удалось отправить отчёт в ops")
            return False

    async def _notify_ops(self, text: str) -> None:
        destination = resolve_service_destination(self._config, "ops")
        try:
            await deliver_service_message(self._bot, destination, text)
        except Exception:
            logger.exception("Не удалось отправить итог отчёта в ops")


def register_report_scheduler(dp, scheduler: ReportScheduler) -> None:
    """Подключает цикл отчётов к startup/shutdown. Не стартует при импорте."""

    async def _start(_dispatcher=None) -> None:
        if not scheduler.owns_loop():
            return
        existing = dp.workflow_data.get("chassis_report_task")
        if existing is not None and not existing.done():
            return
        dp.workflow_data["chassis_report_scheduler"] = scheduler
        dp.workflow_data["chassis_report_task"] = asyncio.create_task(scheduler.loop())

    async def _stop(_dispatcher=None) -> None:
        scheduler.stop()
        task = dp.workflow_data.pop("chassis_report_task", None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    dp.startup.register(_start)
    dp.shutdown.register(_stop)
