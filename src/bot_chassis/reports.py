"""Агрегаты рамы для вечернего отчёта. Метрик кузова здесь нет."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .policies import ReportingPolicy
from .storage import Storage
from .storage.engine import parse_utc


def as_utc_stamp(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def daily_period_start(
    slot_utc: datetime,
    policy: ReportingPolicy,
    previous_scheduled_for: str | None,
    first_scheduled_for: str | None = None,
) -> datetime:
    """Конец прошлого успешного слота, иначе полночь дня слота или reporting_started_at."""

    slot = _aware(slot_utc)
    if previous_scheduled_for:
        return parse_utc(previous_scheduled_for)
    first_slot = parse_utc(first_scheduled_for) if first_scheduled_for else slot
    local = first_slot.astimezone(policy.tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    started = policy.reporting_started_at
    if started is not None:
        started = _aware(started).astimezone(policy.tz)
        if started > midnight:
            return min(started.astimezone(timezone.utc), slot)
    return midnight.astimezone(timezone.utc)


def week_bounds_utc(slot_utc: datetime, policy: ReportingPolicy) -> tuple[datetime, datetime]:
    local = _aware(slot_utc).astimezone(policy.tz)
    monday = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
    return monday.astimezone(timezone.utc), (monday + timedelta(days=7)).astimezone(timezone.utc)


def month_bounds_utc(slot_utc: datetime, policy: ReportingPolicy) -> tuple[datetime, datetime]:
    local = _aware(slot_utc).astimezone(policy.tz)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def is_sunday(slot_utc: datetime, policy: ReportingPolicy) -> bool:
    return _aware(slot_utc).astimezone(policy.tz).weekday() == 6


def is_month_end(slot_utc: datetime, policy: ReportingPolicy) -> bool:
    local = _aware(slot_utc).astimezone(policy.tz)
    return (local.date() + timedelta(days=1)).month != local.month


def format_local(value: datetime, policy: ReportingPolicy) -> str:
    return _aware(value).astimezone(policy.tz).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True, slots=True)
class BotAudience:
    origin_bot_id: str
    telegram_bot_id: int
    active: int
    stopped: int
    deleted: int
    unknown: int
    first_launches: int


@dataclass(frozen=True, slots=True)
class ChassisAggregates:
    period_start: datetime
    period_end: datetime
    new_users: int
    banned: int
    shadow_banned: int
    paid_count: int
    paid_stars: int
    refunded_count: int
    refunded_stars: int
    payment_errors: int
    donation_count: int
    donation_stars: int
    tickets_created: int
    tickets_open: int
    tickets_in_progress: int
    tickets_closed: int
    backup_done: int
    backup_failed: int
    last_backup_details: str | None
    job_failures: int
    restarts: int
    chassis_errors: int
    per_bot: tuple[BotAudience, ...]


def _count(conn, sql: str, params: tuple) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


async def collect_chassis_aggregates(
    storage: Storage,
    bot_id: str,
    period_start: datetime,
    period_end: datetime,
    *,
    donation_sku_codes: Sequence[str] = (),
) -> ChassisAggregates:
    start = as_utc_stamp(period_start)
    end = as_utc_stamp(period_end)
    donations = tuple(donation_sku_codes)
    process = storage.bot_statuses.process

    def _op(conn) -> ChassisAggregates:
        new_users = _count(
            conn,
            "SELECT COUNT(*) FROM users WHERE bot_id = ? AND created_at >= ? AND created_at < ?",
            (bot_id, start, end),
        )
        banned = _count(conn, "SELECT COALESCE(SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END), 0) FROM users WHERE bot_id = ?", (bot_id,))
        shadow = _count(
            conn,
            "SELECT COALESCE(SUM(CASE WHEN is_shadow_banned = 1 THEN 1 ELSE 0 END), 0) FROM users WHERE bot_id = ?",
            (bot_id,),
        )
        paid = conn.execute(
            """
            SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS stars
            FROM transactions
            WHERE bot_id = ? AND provider = 'telegram_stars' AND status = 'paid'
              AND created_at >= ? AND created_at < ?
            """,
            (bot_id, start, end),
        ).fetchone()
        refunded = conn.execute(
            """
            SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS stars
            FROM transactions
            WHERE bot_id = ? AND provider = 'telegram_stars' AND status = 'refunded'
              AND updated_at >= ? AND updated_at < ?
            """,
            (bot_id, start, end),
        ).fetchone()
        if donations:
            placeholders = ",".join("?" * len(donations))
            donation_row = conn.execute(
                f"""
                SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS stars
                FROM transactions
                WHERE bot_id = ? AND provider = 'telegram_stars' AND status = 'paid'
                  AND created_at >= ? AND created_at < ?
                  AND sku_code IN ({placeholders})
                """,
                (bot_id, start, end, *donations),
            ).fetchone()
        else:
            donation_row = {"n": 0, "stars": 0}
        tickets_created = _count(
            conn,
            """
            SELECT COUNT(*) FROM support_threads
            WHERE bot_id = ? AND message_role = 'header'
              AND created_at >= ? AND created_at < ?
            """,
            (bot_id, start, end),
        )
        tickets_open = _count(
            conn,
            """
            SELECT COUNT(*) FROM support_threads
            WHERE bot_id = ? AND message_role = 'header' AND ticket_status = 'open'
            """,
            (bot_id,),
        )
        tickets_progress = _count(
            conn,
            """
            SELECT COUNT(*) FROM support_threads
            WHERE bot_id = ? AND message_role = 'header' AND ticket_status = 'in_progress'
            """,
            (bot_id,),
        )
        tickets_closed = _count(
            conn,
            """
            SELECT COUNT(*) FROM support_threads
            WHERE bot_id = ? AND message_role = 'header' AND ticket_status = 'closed'
              AND COALESCE(closed_at, updated_at) >= ? AND COALESCE(closed_at, updated_at) < ?
            """,
            (bot_id, start, end),
        )
        backup_done = _count(
            conn,
            """
            SELECT COUNT(*) FROM scheduled_job_runs
            WHERE bot_id = ? AND job_key = 'backup.daily' AND status = 'done'
              AND COALESCE(completed_at, started_at) >= ? AND COALESCE(completed_at, started_at) < ?
            """,
            (bot_id, start, end),
        )
        backup_failed = _count(
            conn,
            """
            SELECT COUNT(*) FROM scheduled_job_runs
            WHERE bot_id = ? AND job_key = 'backup.daily' AND status = 'failed'
              AND COALESCE(completed_at, started_at) >= ? AND COALESCE(completed_at, started_at) < ?
            """,
            (bot_id, start, end),
        )
        last_backup = conn.execute(
            """
            SELECT details FROM scheduled_job_runs
            WHERE bot_id = ? AND job_key = 'backup.daily' AND status = 'done'
            ORDER BY scheduled_for DESC LIMIT 1
            """,
            (bot_id,),
        ).fetchone()
        job_failures = _count(
            conn,
            """
            SELECT COUNT(*) FROM scheduled_job_runs
            WHERE bot_id = ? AND status = 'failed'
              AND COALESCE(completed_at, started_at) >= ? AND COALESCE(completed_at, started_at) < ?
            """,
            (bot_id, start, end),
        )
        restarts = _count(
            conn,
            """
            SELECT COUNT(*) FROM scheduled_job_runs
            WHERE bot_id = ? AND job_key LIKE 'process.%'
              AND COALESCE(completed_at, started_at) >= ? AND COALESCE(completed_at, started_at) < ?
            """,
            (bot_id, start, end),
        )
        payment_errors = _count(
            conn,
            """
            SELECT COUNT(*) FROM chassis_events
            WHERE bot_id = ? AND event_type = 'payment_error'
              AND created_at >= ? AND created_at < ?
            """,
            (bot_id, start, end),
        )
        chassis_errors = _count(
            conn,
            """
            SELECT COUNT(*) FROM chassis_events
            WHERE bot_id = ? AND event_type IN ('handler_error', 'delivery_error')
              AND created_at >= ? AND created_at < ?
            """,
            (bot_id, start, end),
        )
        bots: dict[tuple[str, int], dict[str, int]] = {}
        for row in conn.execute(
            """
            SELECT origin_bot_id, telegram_bot_id, status, COUNT(*) AS n
            FROM user_bot_statuses
            WHERE bot_id = ?
            GROUP BY origin_bot_id, telegram_bot_id, status
            """,
            (bot_id,),
        ):
            key = (str(row["origin_bot_id"]), int(row["telegram_bot_id"]))
            bucket = bots.setdefault(key, {"active": 0, "stopped": 0, "deleted": 0, "first": 0})
            status = str(row["status"])
            if status in bucket:
                bucket[status] = int(row["n"])
        for row in conn.execute(
            """
            SELECT origin_bot_id, telegram_bot_id, COUNT(*) AS n
            FROM user_bot_statuses
            WHERE bot_id = ? AND first_launch_notified_at >= ?
              AND first_launch_notified_at < ?
            GROUP BY origin_bot_id, telegram_bot_id
            """,
            (bot_id, start, end),
        ):
            key = (str(row["origin_bot_id"]), int(row["telegram_bot_id"]))
            bucket = bots.setdefault(key, {"active": 0, "stopped": 0, "deleted": 0, "first": 0})
            bucket["first"] = int(row["n"])
        if process is not None:
            bots.setdefault(
                (process.origin_bot_id, process.telegram_bot_id),
                {"active": 0, "stopped": 0, "deleted": 0, "first": 0},
            )
        total_users = _count(conn, "SELECT COUNT(*) FROM users WHERE bot_id = ?", (bot_id,))
        audiences = []
        for (origin, telegram_id), counts in sorted(bots.items(), key=lambda item: (item[0][0], item[0][1])):
            known = _count(
                conn,
                "SELECT COUNT(*) FROM user_bot_statuses WHERE bot_id = ? AND telegram_bot_id = ?",
                (bot_id, telegram_id),
            )
            audiences.append(
                BotAudience(
                    origin_bot_id=origin,
                    telegram_bot_id=telegram_id,
                    active=counts["active"],
                    stopped=counts["stopped"],
                    deleted=counts["deleted"],
                    unknown=max(0, total_users - known),
                    first_launches=counts["first"],
                )
            )
        if not audiences:
            audiences.append(
                BotAudience(
                    origin_bot_id="—",
                    telegram_bot_id=0,
                    active=0,
                    stopped=0,
                    deleted=0,
                    unknown=total_users,
                    first_launches=0,
                )
            )
        return ChassisAggregates(
            period_start=_aware(period_start),
            period_end=_aware(period_end),
            new_users=new_users,
            banned=int(banned),
            shadow_banned=int(shadow),
            paid_count=int(paid["n"]),
            paid_stars=int(paid["stars"]),
            refunded_count=int(refunded["n"]),
            refunded_stars=int(refunded["stars"]),
            payment_errors=payment_errors,
            donation_count=int(donation_row["n"]),
            donation_stars=int(donation_row["stars"]),
            tickets_created=tickets_created,
            tickets_open=tickets_open,
            tickets_in_progress=tickets_progress,
            tickets_closed=tickets_closed,
            backup_done=backup_done,
            backup_failed=backup_failed,
            last_backup_details=(str(last_backup["details"]) if last_backup and last_backup["details"] else None),
            job_failures=job_failures,
            restarts=restarts,
            chassis_errors=chassis_errors,
            per_bot=tuple(audiences),
        )

    return await storage.engine.run(_op)


def _backup_status(block: ChassisAggregates) -> str:
    suffix = (
        ""
        if not block.last_backup_details
        else " (последний архив: "
        f"<b>{html.escape(Path(block.last_backup_details).stem)}</b>)"
    )
    if block.backup_done and not block.backup_failed:
        return f"🟢 успешно — запусков <b>{block.backup_done}</b>{suffix}"
    if block.backup_done and block.backup_failed:
        return f"🟡 частично — успешно <b>{block.backup_done}</b> · ошибок <b>{block.backup_failed}</b>{suffix}"
    if block.backup_failed:
        return f"🔴 ошибка — неуспешных запусков <b>{block.backup_failed}</b>"
    return "⚪ не запускался"


def format_aggregates(
    block: ChassisAggregates,
    policy: ReportingPolicy,
    *,
    title: str,
    project_label: str,
    current_origin_bot_id: str,
    current_telegram_bot_id: int,
) -> str:
    lines = [
        title,
        f"Период: {format_local(block.period_start, policy)} — "
        f"{format_local(block.period_end, policy)} ({policy.tz_label})",
        "",
        "👥 <b>Аудитория</b>",
        f"• Новые пользователи: <b>{block.new_users}</b>",
    ]
    for item in block.per_bot:
        label = (
            project_label
            if (item.origin_bot_id, item.telegram_bot_id)
            == (current_origin_bot_id, current_telegram_bot_id)
            else f"{item.origin_bot_id} / bot {item.telegram_bot_id}"
        )
        lines.append(
            f"• Живая база ({html.escape(label)}): активных <b>{item.active}</b> · "
            f"остановлено <b>{item.stopped}</b> · удалено <b>{item.deleted}</b> · "
            f"неизвестно <b>{item.unknown}</b> · первые запуски "
            f"<b>{item.first_launches}</b>"
        )
    lines.extend(
        [
            f"• Санкции: баны <b>{block.banned}</b> · "
            f"теневые <b>{block.shadow_banned}</b>",
            "",
            "⭐️ <b>Финансы и поддержка</b>",
            f"• Оплаты Stars: <b>{block.paid_stars} ⭐</b> ({block.paid_count} шт.) · "
            f"возвраты: <b>{block.refunded_stars} ⭐</b> ({block.refunded_count} шт.)",
            f"• Ошибки оплат: <b>{block.payment_errors}</b>",
            f"• Донаты Stars: <b>{block.donation_stars} ⭐</b> "
            f"({block.donation_count} шт.)",
            f"• Обращения: создано <b>{block.tickets_created}</b> · "
            f"открыто <b>{block.tickets_open}</b> · "
            f"в работе <b>{block.tickets_in_progress}</b> · "
            f"закрыто <b>{block.tickets_closed}</b>",
            "",
            "💾 <b>Системные задания</b>",
            f"• Ночной бэкап: {_backup_status(block)}",
            f"• Ошибки планировщика: <b>{block.job_failures}</b> · "
            f"Ошибки рамы: <b>{block.chassis_errors}</b>",
            f"• Рестарты процессов: <b>{block.restarts}</b>",
        ]
    )
    return "\n".join(lines)


def format_chassis_report(
    daily: ChassisAggregates,
    policy: ReportingPolicy,
    *,
    weekly: ChassisAggregates | None = None,
    monthly: ChassisAggregates | None = None,
    slot_utc: datetime,
    project_label: str = "Сервис",
    current_origin_bot_id: str = "",
    current_telegram_bot_id: int = 0,
) -> str:
    parts = [
        format_aggregates(
            daily,
            policy,
            title="📋 <b>Суточный отчёт рамы</b>",
            project_label=project_label,
            current_origin_bot_id=current_origin_bot_id,
            current_telegram_bot_id=current_telegram_bot_id,
        )
    ]
    if weekly is not None:
        parts.append(
            format_aggregates(
                weekly,
                policy,
                title="📋 <b>Недельный отчёт рамы</b>",
                project_label=project_label,
                current_origin_bot_id=current_origin_bot_id,
                current_telegram_bot_id=current_telegram_bot_id,
            )
        )
    if monthly is not None:
        parts.append(
            format_aggregates(
                monthly,
                policy,
                title="📋 <b>Месячный отчёт рамы</b>",
                project_label=project_label,
                current_origin_bot_id=current_origin_bot_id,
                current_telegram_bot_id=current_telegram_bot_id,
            )
        )
    return "\n\n".join(parts)
