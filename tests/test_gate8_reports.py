"""Gate 8: chassis evening reports, period bounds, one claim per network."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, User

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.factory import create_complete_chassis
from bot_chassis.policies import REPORT_JOB_KEY, ReportingPolicy, UTC_PLUS_5
from bot_chassis.reports import (
    BotAudience,
    ChassisAggregates,
    collect_chassis_aggregates,
    daily_period_start,
    format_chassis_report,
    is_month_end,
    is_sunday,
)
from bot_chassis.scheduler import ReportScheduler, due_slot_utc, slot_key
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import StorageEngine
from bot_chassis.storage.repositories.scheduled_jobs import ScheduledJobRunsRepository


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name in {"SendMessage", "EditMessageText"}:
            return Message(
                message_id=len(self.requests),
                date=1,
                chat=Chat(id=getattr(method, "chat_id", 0) or 7, type="private"),
                text=getattr(method, "text", "") or "",
            )
        return True

    async def stream_content(self, url: str, headers=None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _stamp(local: datetime) -> str:
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _aggregate(**changes) -> ChassisAggregates:
    base = ChassisAggregates(
        period_start=datetime(2026, 10, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 10, 2, tzinfo=timezone.utc),
        new_users=1,
        banned=2,
        shadow_banned=3,
        paid_count=4,
        paid_stars=5,
        refunded_count=6,
        refunded_stars=7,
        payment_errors=8,
        donation_count=9,
        donation_stars=10,
        tickets_created=11,
        tickets_open=12,
        tickets_in_progress=13,
        tickets_closed=14,
        backup_done=15,
        backup_failed=0,
        last_backup_details="daily_<archive>.zip",
        job_failures=16,
        restarts=17,
        chassis_errors=18,
        per_bot=(),
    )
    return replace(base, **changes)


class TestGate8Reports(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "live.db")
        self.config = BotChassisConfig(
            bot_id="tenant",
            db_path=self.db_path,
            origin_bot_id="psy",
            audit_chat_id=-100,
            events_thread_id=11,
            ops_thread_id=12,
            superadmin_ids=(100,),
            skus=(
                SkuItem(sku_code="vip", title="VIP", description="x", stars_price=100),
                SkuItem(sku_code="donate_50", title="D", description="d", stars_price=50, issues_voucher=False),
            ),
        )
        self.storage = await create_storage(self.config)
        self.storage.bot_statuses.bind_process("psy", 1)
        self.policy = ReportingPolicy()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _set_created(self, user_id: int, when: datetime, *, bot_id: str = "tenant") -> None:
        await self.storage.users.upsert_user(bot_id, user_id, username=f"u{user_id}")
        stamp = _stamp(when)

        def _op(conn) -> None:
            conn.execute(
                "UPDATE users SET created_at = ?, updated_at = ? WHERE bot_id = ? AND user_id = ?",
                (stamp, stamp, bot_id, user_id),
            )

        await self.storage.engine.run(_op)

    async def test_first_period_midnight_started_at_and_no_history_dump(self) -> None:
        monday_slot = datetime(2026, 10, 5, 23, 30, tzinfo=UTC_PLUS_5)
        await self._set_created(1, datetime(2026, 1, 1, 12, 0, tzinfo=UTC_PLUS_5))
        await self._set_created(2, datetime(2026, 10, 5, 1, 0, tzinfo=UTC_PLUS_5))
        await self._set_created(3, datetime(2026, 10, 5, 20, 0, tzinfo=UTC_PLUS_5))
        await self._set_created(99, datetime(2026, 10, 5, 1, 0, tzinfo=UTC_PLUS_5), bot_id="other")

        start = daily_period_start(monday_slot.astimezone(timezone.utc), self.policy, None)
        self.assertEqual(start, datetime(2026, 10, 4, 19, 0, tzinfo=timezone.utc))
        daily = await collect_chassis_aggregates(self.storage, "tenant", start, monday_slot, donation_sku_codes=("donate_50",))
        self.assertEqual(daily.new_users, 2)
        self.assertNotIn("other", "".join(item.origin_bot_id for item in daily.per_bot))

        late = ReportingPolicy(reporting_started_at=datetime(2026, 10, 5, 18, 0, tzinfo=UTC_PLUS_5))
        late_start = daily_period_start(monday_slot.astimezone(timezone.utc), late, None)
        late_daily = await collect_chassis_aggregates(self.storage, "tenant", late_start, monday_slot)
        self.assertEqual(late_daily.new_users, 1)

        friday_key = slot_key(due_slot_utc(datetime(2026, 10, 2, 23, 30, tzinfo=UTC_PLUS_5), self.policy))
        await self.storage.scheduled_jobs.claim("tenant", REPORT_JOB_KEY, friday_key, "old")
        await self.storage.scheduled_jobs.mark_status("tenant", REPORT_JOB_KEY, friday_key, "done", complete=True)
        sunday_slot = datetime(2026, 10, 4, 23, 30, tzinfo=UTC_PLUS_5)
        gap_start = daily_period_start(sunday_slot.astimezone(timezone.utc), self.policy, friday_key)
        self.assertEqual(gap_start, datetime(2026, 10, 2, 18, 30, tzinfo=timezone.utc))
        await self._set_created(4, datetime(2026, 10, 3, 12, 0, tzinfo=UTC_PLUS_5))
        gap = await collect_chassis_aggregates(self.storage, "tenant", gap_start, sunday_slot)
        self.assertGreaterEqual(gap.new_users, 1)

    async def test_first_start_before_slot_waits_and_period_never_reverses(self) -> None:
        monday_morning = datetime(2026, 10, 5, 10, 0, tzinfo=UTC_PLUS_5)
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        scheduler = ReportScheduler(
            bot=bot,
            config=self.config,
            storage=self.storage,
            policy=ReportingPolicy(reporting_started_at=monday_morning),
            origin_bot_id="psy",
            telegram_bot_id=1,
        )
        self.assertIsNone(await scheduler.run_due(monday_morning))
        rows = await self.storage.engine.run(
            lambda conn: conn.execute(
                "SELECT COUNT(*) FROM scheduled_job_runs WHERE job_key = ?",
                (REPORT_JOB_KEY,),
            ).fetchone()[0]
        )
        self.assertEqual(rows, 0)
        stale_slot = due_slot_utc(monday_morning, self.policy)
        start = daily_period_start(
            stale_slot,
            ReportingPolicy(reporting_started_at=monday_morning),
            None,
        )
        self.assertLessEqual(start, stale_slot)
        await bot.session.close()

    async def test_first_launch_and_immutable_error_events_use_period_timestamp(self) -> None:
        await self._set_created(20, datetime(2026, 9, 1, 12, 0, tzinfo=UTC_PLUS_5))
        await self.storage.bot_statuses.mark_active("tenant", 20, "psy", 1)
        marker = _stamp(datetime(2026, 10, 5, 12, 0, tzinfo=UTC_PLUS_5))
        await self.storage.engine.run(
            lambda conn: conn.execute(
                """
                UPDATE user_bot_statuses
                SET first_seen_at = '2026-09-01 00:00:00',
                    first_launch_notified_at = ?
                WHERE bot_id = 'tenant' AND user_id = 20 AND telegram_bot_id = 1
                """,
                (marker,),
            )
        )
        await self.storage.events.record("tenant", "payment_error", details="payload_mismatch")
        await self.storage.events.record("tenant", "handler_error", details="RuntimeError")
        # Маркер теста фиксирован, поэтому период строим вокруг него; события переносим туда же.
        await self.storage.engine.run(
            lambda conn: conn.execute(
                "UPDATE chassis_events SET created_at = ? WHERE bot_id = 'tenant'",
                (marker,),
            )
        )
        period_start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC_PLUS_5)
        period_end = datetime(2026, 10, 6, 0, 0, tzinfo=UTC_PLUS_5)
        aggregate = await collect_chassis_aggregates(
            self.storage,
            "tenant",
            period_start,
            period_end,
        )
        self.assertEqual(aggregate.per_bot[0].first_launches, 1)
        self.assertEqual(aggregate.payment_errors, 1)
        self.assertEqual(aggregate.chassis_errors, 1)

    async def test_failed_first_report_keeps_original_period_for_next_slot(self) -> None:
        first_slot = datetime(2026, 10, 5, 23, 30, tzinfo=UTC_PLUS_5)
        first_key = slot_key(due_slot_utc(first_slot, self.policy))
        await self.storage.scheduled_jobs.claim("tenant", REPORT_JOB_KEY, first_key, "failed")
        await self.storage.scheduled_jobs.mark_status(
            "tenant",
            REPORT_JOB_KEY,
            first_key,
            "failed",
            complete=True,
        )
        await self._set_created(30, datetime(2026, 10, 5, 12, 0, tzinfo=UTC_PLUS_5))
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        scheduler = ReportScheduler(
            bot=bot,
            config=self.config,
            storage=self.storage,
            policy=self.policy,
            origin_bot_id="psy",
            telegram_bot_id=1,
        )
        text = await scheduler.run_due(datetime(2026, 10, 6, 23, 30, tzinfo=UTC_PLUS_5))
        self.assertIsNotNone(text)
        self.assertIn("Новые пользователи: <b>1</b>", text)
        self.assertIn("2026-10-05 00:00", text)
        await bot.session.close()

    async def test_seven_claims_one_winner_repeat_skips(self) -> None:
        sunday = datetime(2026, 10, 4, 23, 30, tzinfo=UTC_PLUS_5)
        slot = slot_key(due_slot_utc(sunday, self.policy))
        engines = [StorageEngine(self.db_path) for _ in range(7)]
        repos = [ScheduledJobRunsRepository(engine) for engine in engines]

        async def _claim(index: int) -> bool:
            return await repos[index].claim("tenant", REPORT_JOB_KEY, slot, f"bot-{index}")

        winners = await asyncio.gather(*(_claim(index) for index in range(7)))
        self.assertEqual(sum(1 for item in winners if item), 1)

        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        scheduler = ReportScheduler(
            bot=bot,
            config=self.config,
            storage=self.storage,
            policy=self.policy,
            origin_bot_id="psy",
            telegram_bot_id=1,
            donation_sku_codes=("donate_50",),
        )
        first = await scheduler.run_due(sunday)
        self.assertIsNone(first)
        second = await scheduler.run_due(sunday)
        self.assertIsNone(second)
        await bot.session.close()

    async def test_sunday_week_and_month_end_blocks_without_double_daily(self) -> None:
        self.assertTrue(is_sunday(datetime(2026, 5, 31, 23, 30, tzinfo=UTC_PLUS_5), self.policy))
        self.assertTrue(is_month_end(datetime(2026, 5, 31, 23, 30, tzinfo=UTC_PLUS_5), self.policy))
        self.assertFalse(is_month_end(datetime(2026, 10, 4, 23, 30, tzinfo=UTC_PLUS_5), self.policy))

        await self._set_created(10, datetime(2026, 5, 31, 10, 0, tzinfo=UTC_PLUS_5))
        await self.storage.bot_statuses.set_active("tenant", 10, "psy", 1)
        await self.storage.engine.run(
            lambda conn: conn.execute(
                """
                INSERT INTO transactions (
                    bot_id, user_id, provider, payment_id, telegram_payment_charge_id,
                    merchant_origin_bot_id, merchant_telegram_bot_id, sku_code, amount,
                    currency, status, voucher_id, voucher_status, created_at, updated_at
                ) VALUES
                ('tenant', 10, 'telegram_stars', 'p1', 'p1', 'psy', 1, 'vip', 100, 'XTR', 'paid', 'v1', 'issued', ?, ?),
                ('tenant', 10, 'telegram_stars', 'p2', 'p2', 'psy', 1, 'donate_50', 50, 'XTR', 'paid', 'v2', 'issued', ?, ?)
                """,
                (_stamp(datetime(2026, 5, 31, 12, 0, tzinfo=UTC_PLUS_5)),) * 4,
            )
        )
        await self.storage.engine.run(
            lambda conn: conn.execute(
                """
                INSERT INTO support_threads (
                    bot_id, support_chat_id, support_message_id, user_id, origin_bot_id,
                    origin_telegram_bot_id, ticket_id, message_role, ticket_status, created_at, updated_at
                ) VALUES
                ('tenant', -100, 1, 10, 'psy', 1, 't1', 'header', 'open', ?, ?),
                ('tenant', -100, 2, 10, 'psy', 1, 't2', 'header', 'closed', ?, ?)
                """,
                (
                    _stamp(datetime(2026, 5, 31, 11, 0, tzinfo=UTC_PLUS_5)),
                    _stamp(datetime(2026, 5, 31, 11, 0, tzinfo=UTC_PLUS_5)),
                    _stamp(datetime(2026, 5, 31, 11, 0, tzinfo=UTC_PLUS_5)),
                    _stamp(datetime(2026, 5, 31, 16, 0, tzinfo=UTC_PLUS_5)),
                ),
            )
        )
        await self.storage.engine.run(
            lambda conn: conn.execute(
                "UPDATE support_threads SET closed_at = ? WHERE ticket_id = 't2'",
                (_stamp(datetime(2026, 5, 31, 16, 0, tzinfo=UTC_PLUS_5)),),
            )
        )

        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        scheduler = ReportScheduler(
            bot=bot,
            config=self.config,
            storage=self.storage,
            policy=self.policy,
            origin_bot_id="psy",
            telegram_bot_id=1,
            donation_sku_codes=("donate_50",),
        )
        text = await scheduler.run_due(datetime(2026, 5, 31, 23, 30, tzinfo=UTC_PLUS_5))
        self.assertIsNotNone(text)
        self.assertEqual(text.count("отчёт рамы"), 3)
        self.assertIn("Недельный отчёт рамы", text)
        self.assertIn("Месячный отчёт рамы", text)
        self.assertIn("Донаты Stars: <b>50 ⭐</b> (1 шт.)", text)
        self.assertIn("Оплаты Stars: <b>150 ⭐</b> (2 шт.)", text)
        events = [
            item
            for item in session.requests
            if item.__class__.__name__ == "SendMessage" and getattr(item, "message_thread_id", None) == 11
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].text, text)
        self.assertEqual(events[0].parse_mode, "HTML")
        weekday = await scheduler.run_due(datetime(2026, 10, 5, 23, 30, tzinfo=UTC_PLUS_5))
        self.assertIsNotNone(weekday)
        self.assertNotIn("Недельный итог", weekday)
        self.assertNotIn("Месячный итог", weekday)
        await bot.session.close()

    async def test_delivery_failure_goes_to_ops_and_owner_skips(self) -> None:
        sunday = datetime(2026, 10, 4, 23, 30, tzinfo=UTC_PLUS_5)
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        scheduler = ReportScheduler(
            bot=bot,
            config=self.config,
            storage=self.storage,
            policy=self.policy,
            origin_bot_id="psy",
            telegram_bot_id=1,
        )

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("events down")

        with patch("bot_chassis.scheduler.deliver_service_message", new=AsyncMock(side_effect=_boom)):
            result = await scheduler.run_due(sunday)
        self.assertIsNone(result)
        record = await self.storage.scheduled_jobs.get(
            "tenant", REPORT_JOB_KEY, slot_key(due_slot_utc(sunday, self.policy))
        )
        self.assertEqual(record["status"], "failed")

        foreign = ReportScheduler(
            bot=bot,
            config=self.config,
            storage=self.storage,
            policy=ReportingPolicy(scheduler_owner_origin_bot_id="owner"),
            origin_bot_id="other",
            telegram_bot_id=2,
        )
        self.assertIsNone(await foreign.run_due(sunday))
        await bot.session.close()

    async def test_factory_none_skips_report_loop(self) -> None:
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        config = BotChassisConfig(bot_id="tenant", db_path=self.db_path, enable_admin=False, enable_payments=False)
        with (
            patch(
                "bot_chassis.scheduler.BackupScheduler.run_due",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "bot_chassis.scheduler.ReportScheduler.run_due",
                new=AsyncMock(return_value=None),
            ),
        ):
            plain = await create_complete_chassis(bot, config)
            await plain.dp.emit_startup(bot=bot)
            self.assertIsNone(plain.dp.workflow_data.get("chassis_report_task"))
            await plain.dp.emit_shutdown(bot=bot)
            armed = await create_complete_chassis(bot, config, reporting_policy=self.policy)
            await armed.dp.emit_startup(bot=bot)
            task = armed.dp.workflow_data.get("chassis_report_task")
            self.assertIsNotNone(task)
            self.assertIsNotNone(armed.dp.workflow_data.get("chassis_backup_task"))
            await armed.dp.emit_shutdown(bot=bot)
            self.assertTrue(task.cancelled() or task.done())
            self.assertIsNone(armed.dp.workflow_data.get("chassis_backup_task"))
        await bot.session.close()


class TestA7ReportFormatting(unittest.TestCase):
    def test_report_renders_each_per_bot_row_without_folding(self) -> None:
        block = _aggregate(
            per_bot=(
                BotAudience("origin", 1, 2, 3, 4, 5, 6),
                BotAudience("<other>", 2, 7, 8, 9, 10, 11),
            )
        )
        text = format_chassis_report(
            block,
            ReportingPolicy(),
            slot_utc=block.period_end,
            project_label="<Main>",
            current_origin_bot_id="origin",
            current_telegram_bot_id=1,
        )
        self.assertEqual(text.count("• Живая база ("), 2)
        self.assertIn("Живая база (&lt;Main&gt;): активных <b>2</b>", text)
        self.assertIn("Живая база (&lt;other&gt; / bot 2): активных <b>7</b>", text)

    def test_report_backup_status_all_four_branches(self) -> None:
        cases = (
            (_aggregate(backup_done=1, backup_failed=0), "🟢 успешно — запусков <b>1</b>"),
            (_aggregate(backup_done=1, backup_failed=2), "🟡 частично — успешно <b>1</b> · ошибок <b>2</b>"),
            (_aggregate(backup_done=0, backup_failed=2), "🔴 ошибка — неуспешных запусков <b>2</b>"),
            (_aggregate(backup_done=0, backup_failed=0), "⚪ не запускался"),
        )
        for block, expected in cases:
            text = format_chassis_report(
                block, ReportingPolicy(), slot_utc=block.period_end
            )
            self.assertIn(f"• Ночной бэкап: {expected}", text)
        success = format_chassis_report(
            cases[0][0], ReportingPolicy(), slot_utc=cases[0][0].period_end
        )
        self.assertIn("последний архив: <b>daily_&lt;archive&gt;</b>", success)

    def test_report_exact_human_labels_keep_every_aggregate(self) -> None:
        block = _aggregate()
        text = format_chassis_report(
            block, ReportingPolicy(), slot_utc=block.period_end
        )
        expected_lines = (
            "• Новые пользователи: <b>1</b>",
            "• Санкции: баны <b>2</b> · теневые <b>3</b>",
            "• Оплаты Stars: <b>5 ⭐</b> (4 шт.) · возвраты: <b>7 ⭐</b> (6 шт.)",
            "• Ошибки оплат: <b>8</b>",
            "• Донаты Stars: <b>10 ⭐</b> (9 шт.)",
            "• Обращения: создано <b>11</b> · открыто <b>12</b> · в работе <b>13</b> · закрыто <b>14</b>",
            "• Ошибки планировщика: <b>16</b> · Ошибки рамы: <b>18</b>",
            "• Рестарты процессов: <b>17</b>",
        )
        for line in expected_lines:
            self.assertEqual(text.count(line), 1, line)


if __name__ == "__main__":
    unittest.main()
