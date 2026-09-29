"""Gate 7: verified backup, rotation, scheduler claim, WAL retry."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from bot_chassis.admin.router import create_admin_router
from bot_chassis.config import BotChassisConfig
from bot_chassis.factory import create_complete_chassis
from bot_chassis.policies import BACKUP_JOB_KEY, BackupPolicy
from bot_chassis.scheduler import BackupScheduler, due_slot_utc, register_backup_scheduler, slot_key
from bot_chassis.storage import create_storage
from bot_chassis.storage.backup import (
    ARCHIVE_DB_NAME,
    BackupError,
    create_nightly_archive,
    verify_sqlite,
)
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
        if name == "SendDocument":
            doc = getattr(method, "document", None)
            from aiogram.types import FSInputFile

            if isinstance(doc, FSInputFile):
                method._test_payload = Path(doc.path).read_bytes()
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


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="N")


class TestGate7Backup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "live.db")
        self.catalog = os.path.join(self._tmp.name, "archives")
        self.storage = await create_storage(
            BotChassisConfig(bot_id="tenant", db_path=self.db_path, superadmin_ids=(100,))
        )
        await self.storage.users.upsert_user("tenant", 7, username="ann")
        self.policy = BackupPolicy(directory=self.catalog, daily_keep=2, weekly_keep=2, retry_attempts=4, retry_base_delay=0.01, timeout_seconds=5)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_wal_archive_restores_and_seven_claims_have_one_winner(self) -> None:
        mode = await self.storage.engine.run(lambda conn: conn.execute("PRAGMA journal_mode").fetchone()[0])
        self.assertEqual(str(mode).lower(), "wal")
        monday = datetime(2026, 10, 5, 4, 0, tzinfo=self.policy.tz)
        result = await create_nightly_archive(self.storage.engine, self.policy, monday)
        self.assertTrue(result.path.name.startswith("daily_"))
        self.assertTrue(result.path.name.endswith("UTC+5.zip"))
        with zipfile.ZipFile(result.path) as archive:
            self.assertEqual(archive.namelist(), [ARCHIVE_DB_NAME])
            extracted = Path(self._tmp.name) / "restored.db"
            extracted.write_bytes(archive.read(ARCHIVE_DB_NAME))
        self.assertTrue(verify_sqlite(extracted))
        conn = sqlite3.connect(extracted)
        try:
            row = conn.execute("SELECT username FROM users WHERE user_id = 7").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "ann")

        slot = slot_key(due_slot_utc(monday, self.policy))
        engines = [StorageEngine(self.db_path) for _ in range(7)]
        repos = [ScheduledJobRunsRepository(engine) for engine in engines]

        async def _claim(index: int) -> bool:
            return await repos[index].claim("tenant", BACKUP_JOB_KEY, slot, f"bot-{index}")

        winners = await asyncio.gather(*(_claim(index) for index in range(7)))
        self.assertEqual(sum(1 for item in winners if item), 1)
        record = await self.storage.scheduled_jobs.get("tenant", BACKUP_JOB_KEY, slot)
        self.assertIsNotNone(record)
        self.assertEqual(record["status"], "claimed")

    async def test_corrupt_snapshot_does_not_rotate_existing(self) -> None:
        Path(self.catalog).mkdir(parents=True, exist_ok=True)
        keeper = Path(self.catalog) / "daily_2026-10-01_04-00-00_UTC+5.zip"
        keeper.write_bytes(b"keep")
        monday = datetime(2026, 10, 5, 4, 0, tzinfo=self.policy.tz)

        async def _broken(dest_path: str, **_kwargs) -> None:
            Path(dest_path).write_bytes(b"not a sqlite database")

        with patch.object(self.storage.engine, "backup", new=AsyncMock(side_effect=_broken)):
            with self.assertRaises(BackupError):
                await create_nightly_archive(self.storage.engine, self.policy, monday)
        self.assertTrue(keeper.exists())
        self.assertEqual(
            [path.name for path in Path(self.catalog).glob("*.zip")],
            ["daily_2026-10-01_04-00-00_UTC+5.zip"],
        )

    async def test_stale_unfinished_claim_is_recovered_and_old_owner_is_fenced(self) -> None:
        slot = "2026-10-05 23:00:00"
        repo = self.storage.scheduled_jobs
        self.assertTrue(await repo.claim("tenant", BACKUP_JOB_KEY, slot, "old-owner"))
        await repo.mark_status("tenant", BACKUP_JOB_KEY, slot, "running")
        await self.storage.engine.run(
            lambda conn: conn.execute(
                """
                UPDATE scheduled_job_runs SET started_at = '2000-01-01 00:00:00'
                WHERE bot_id = ? AND job_key = ? AND scheduled_for = ?
                """,
                ("tenant", BACKUP_JOB_KEY, slot),
            )
        )

        self.assertTrue(
            await repo.claim(
                "tenant",
                BACKUP_JOB_KEY,
                slot,
                "new-owner",
                stale_after_seconds=15 * 60,
            )
        )
        self.assertFalse(
            await repo.claim(
                "tenant",
                BACKUP_JOB_KEY,
                slot,
                "third-owner",
                stale_after_seconds=15 * 60,
            )
        )
        self.assertEqual(
            await repo.mark_status(
                "tenant",
                BACKUP_JOB_KEY,
                slot,
                "done",
                complete=True,
                expected_claimed_by="old-owner",
            ),
            0,
        )
        self.assertEqual(
            await repo.mark_status(
                "tenant",
                BACKUP_JOB_KEY,
                slot,
                "done",
                complete=True,
                expected_claimed_by="new-owner",
            ),
            1,
        )

    async def test_sunday_rename_is_not_a_second_copy_and_prunes(self) -> None:
        Path(self.catalog).mkdir(parents=True, exist_ok=True)
        for day in range(1, 4):
            (Path(self.catalog) / f"daily_2026-09-0{day}_04-00-00_UTC+5.zip").write_bytes(b"old")
        (Path(self.catalog) / "weekly_2026-09-06_04-00-00_UTC+5.zip").write_bytes(b"w1")
        (Path(self.catalog) / "weekly_2026-09-13_04-00-00_UTC+5.zip").write_bytes(b"w2")
        sunday = datetime(2026, 10, 4, 4, 0, tzinfo=self.policy.tz)
        result = await create_nightly_archive(self.storage.engine, self.policy, sunday)
        self.assertTrue(result.path.name.startswith("weekly_"))
        names = sorted(path.name for path in Path(self.catalog).glob("*.zip"))
        self.assertEqual(len([name for name in names if name.startswith("daily_")]), 2)
        self.assertEqual(len([name for name in names if name.startswith("weekly_")]), 2)
        self.assertIn(result.path.name, names)
        self.assertFalse(any(name.startswith("daily_2026-10-04") for name in names))

    async def test_retry_then_success_and_owner_skips_foreign_loop(self) -> None:
        calls = {"n": 0}

        original = self.storage.engine.backup

        async def _flaky(dest_path: str, **kwargs) -> None:
            calls["n"] += 1
            if calls["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            await original(dest_path, **kwargs)

        monday = datetime(2026, 10, 5, 4, 0, tzinfo=self.policy.tz)
        with patch.object(self.storage.engine, "backup", side_effect=_flaky):
            result = await create_nightly_archive(self.storage.engine, self.policy, monday)
        self.assertGreaterEqual(calls["n"], 3)
        self.assertTrue(result.path.exists())

        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        foreign = BackupScheduler(
            bot=bot,
            config=BotChassisConfig(bot_id="tenant", db_path=self.db_path, origin_bot_id="other"),
            storage=self.storage,
            policy=BackupPolicy(directory=self.catalog, scheduler_owner_origin_bot_id="owner"),
            origin_bot_id="other",
            telegram_bot_id=2,
        )
        self.assertIsNone(await foreign.run_due(monday))
        owner = BackupScheduler(
            bot=bot,
            config=BotChassisConfig(
                bot_id="tenant",
                db_path=self.db_path,
                origin_bot_id="owner",
                audit_chat_id=-100,
                ops_thread_id=9,
            ),
            storage=self.storage,
            policy=BackupPolicy(directory=self.catalog, scheduler_owner_origin_bot_id="owner"),
            origin_bot_id="owner",
            telegram_bot_id=1,
        )
        created = await owner.run_due(monday)
        self.assertIsNotNone(created)
        ops = [item for item in session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertTrue(any("Backup ok" in (getattr(item, "text", "") or "") for item in ops))
        self.assertTrue(all(getattr(item, "chat_id", None) != 7 for item in session.requests if item.__class__.__name__ == "SendDocument"))
        await bot.session.close()

    async def test_factory_none_skips_scheduler_owner_registers_lifecycle(self) -> None:
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        config = BotChassisConfig(bot_id="tenant", db_path=self.db_path, enable_admin=False, enable_payments=False)
        plain = await create_complete_chassis(bot, config)
        await plain.dp.emit_startup(bot=bot)
        self.assertIsNone(plain.dp.workflow_data.get("chassis_backup_task"))
        await plain.dp.emit_shutdown(bot=bot)
        armed = await create_complete_chassis(bot, config, backup_policy=self.policy)
        await armed.dp.emit_startup(bot=bot)
        task = armed.dp.workflow_data.get("chassis_backup_task")
        self.assertIsNotNone(task)
        await armed.dp.emit_shutdown(bot=bot)
        self.assertTrue(task.cancelled() or task.done())
        await bot.session.close()

    async def test_manual_oversize_keeps_catalog_copy_with_size(self) -> None:
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        config = BotChassisConfig(bot_id="tenant", db_path=self.db_path, superadmin_ids=(100,))
        storage = await create_storage(config)
        dp = Dispatcher()
        tiny = BackupPolicy(directory=self.catalog, transport_limit_bytes=1)
        dp.include_router(create_admin_router("tenant", storage, config, backup_policy=tiny))
        await dp.feed_update(
            bot,
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=1,
                    chat=Chat(id=100, type="private"),
                    from_user=_user(100),
                    text="/backup",
                ),
            ),
        )
        self.assertFalse([item for item in session.requests if item.__class__.__name__ == "SendDocument"])
        texts = [item.text for item in session.requests if item.__class__.__name__ == "SendMessage" and item.chat_id == 100]
        self.assertTrue(any("байт" in text and "Копия оставлена" in text for text in texts))
        manuals = list(Path(self.catalog).glob("manual_*.db"))
        self.assertEqual(len(manuals), 1)
        await bot.session.close()

    async def test_policy_deadline_is_passed_into_each_sqlite_backup(self) -> None:
        seen: list[float] = []

        async def _timeout(_dest_path: str, *, timeout_seconds: float) -> None:
            seen.append(timeout_seconds)
            raise TimeoutError("deadline")

        policy = BackupPolicy(
            directory=self.catalog,
            timeout_seconds=0.05,
            retry_attempts=2,
            retry_base_delay=0.0,
        )
        monday = datetime(2026, 10, 5, 4, 0, tzinfo=policy.tz)
        with patch.object(self.storage.engine, "backup", side_effect=_timeout):
            with self.assertRaises(BackupError):
                await create_nightly_archive(self.storage.engine, policy, monday)
        self.assertTrue(seen)
        self.assertTrue(all(0 < value <= max(0.001, policy.timeout_seconds) for value in seen))

    async def test_manual_success_removes_catalog_copy(self) -> None:
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        config = BotChassisConfig(bot_id="tenant", db_path=self.db_path, superadmin_ids=(100,))
        storage = await create_storage(config)
        dp = Dispatcher()
        dp.include_router(create_admin_router("tenant", storage, config, backup_policy=self.policy))
        await dp.feed_update(
            bot,
            Update(
                update_id=2,
                message=Message(
                    message_id=2,
                    date=1,
                    chat=Chat(id=100, type="private"),
                    from_user=_user(100),
                    text="/backup",
                ),
            ),
        )
        self.assertEqual(
            len([item for item in session.requests if item.__class__.__name__ == "SendDocument"]),
            1,
        )
        self.assertEqual(list(Path(self.catalog).glob("manual_*.db")), [])
        await bot.session.close()


if __name__ == "__main__":
    unittest.main()
