"""Политики фоновых задач рамы. Не входят в BotChassisConfig."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


UTC_PLUS_5 = timezone(timedelta(hours=5))
BACKUP_JOB_KEY = "backup.daily"
REPORT_JOB_KEY = "report.daily"
DEFAULT_TRANSPORT_LIMIT = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    """Каталог, пояс UTC+5, окно 04:00 и ротация 14/8 для файловой SQLite."""

    directory: str
    tz_offset_hours: int = 5
    hour: int = 4
    minute: int = 0
    daily_keep: int = 14
    weekly_keep: int = 8
    timeout_seconds: float = 60.0
    retry_attempts: int = 6
    retry_base_delay: float = 0.25
    transport_limit_bytes: int = DEFAULT_TRANSPORT_LIMIT
    scheduler_owner_origin_bot_id: str | None = None
    claim_stale_after_seconds: float = 15 * 60

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(hours=self.tz_offset_hours))

    @property
    def tz_label(self) -> str:
        sign = "+" if self.tz_offset_hours >= 0 else "-"
        return f"UTC{sign}{abs(self.tz_offset_hours)}"


@dataclass(frozen=True, slots=True)
class ReportingPolicy:
    """23:30 UTC+5, events/ops из конфига. None в фабрике = без вечерних отчётов."""

    tz_offset_hours: int = 5
    hour: int = 23
    minute: int = 30
    reporting_started_at: datetime | None = None
    scheduler_owner_origin_bot_id: str | None = None
    claim_stale_after_seconds: float = 15 * 60

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(hours=self.tz_offset_hours))

    @property
    def tz_label(self) -> str:
        sign = "+" if self.tz_offset_hours >= 0 else "-"
        return f"UTC{sign}{abs(self.tz_offset_hours)}"
