"""Проверяемые снимки SQLite: ручной .db и ночной ZIP с ротацией."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .engine import StorageEngine
from ..policies import BackupPolicy

ARCHIVE_DB_NAME = "chassis.db"


class BackupError(RuntimeError):
    """Снимок не прошёл проверку или не уложился в таймаут."""


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    path: Path
    kind: str
    bytes: int


def archive_filename(kind: str, local_when: datetime, tz_label: str) -> str:
    stamp = local_when.strftime("%Y-%m-%d_%H-%M-%S")
    suffix = "zip" if kind in {"daily", "weekly"} else "db"
    return f"{kind}_{stamp}_{tz_label}.{suffix}"


async def write_verified_sqlite(
    engine: StorageEngine,
    dest: str | Path,
    policy: BackupPolicy,
) -> Path:
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_path.with_name(f".tmp-{uuid.uuid4().hex}.db")
    try:
        await _backup_with_retry(engine, tmp, policy)
        if not verify_sqlite(tmp):
            raise BackupError("integrity_check failed")
        os.replace(tmp, dest_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest_path


def verify_sqlite(path: str | Path) -> bool:
    conn = sqlite3.connect(str(path), timeout=10.0)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False
    finally:
        conn.close()


async def create_nightly_archive(
    engine: StorageEngine,
    policy: BackupPolicy,
    local_when: datetime,
) -> SnapshotResult:
    catalog = Path(policy.directory)
    catalog.mkdir(parents=True, exist_ok=True)
    daily_name = archive_filename("daily", local_when, policy.tz_label)
    daily_path = catalog / daily_name
    tmp_db = catalog / f".tmp-{uuid.uuid4().hex}.db"
    tmp_zip = catalog / f".tmp-{uuid.uuid4().hex}.zip"
    try:
        await _backup_with_retry(engine, tmp_db, policy)
        if not verify_sqlite(tmp_db):
            raise BackupError("integrity_check failed")
        _zip_db(tmp_db, tmp_zip)
        os.replace(tmp_zip, daily_path)
    except Exception:
        tmp_zip.unlink(missing_ok=True)
        raise
    finally:
        tmp_db.unlink(missing_ok=True)
    final = _promote_sunday_and_rotate(catalog, daily_path, local_when, policy)
    return SnapshotResult(path=final, kind="weekly" if final.name.startswith("weekly_") else "daily", bytes=final.stat().st_size)


async def write_manual_snapshot(engine: StorageEngine, policy: BackupPolicy) -> Path:
    catalog = Path(policy.directory)
    catalog.mkdir(parents=True, exist_ok=True)
    local_now = datetime.now(policy.tz)
    name = archive_filename("manual", local_now, policy.tz_label)
    return await write_verified_sqlite(engine, catalog / name, policy)


def rotate_only_existing(catalog: str | Path, policy: BackupPolicy) -> None:
    _prune(Path(catalog), "daily_", policy.daily_keep)
    _prune(Path(catalog), "weekly_", policy.weekly_keep)


async def _backup_with_retry(engine: StorageEngine, dest: Path, policy: BackupPolicy) -> None:
    policy_timeout = max(0.001, policy.timeout_seconds)
    deadline = time.monotonic() + policy_timeout
    attempt = 0
    last: Exception | None = None
    while attempt < max(1, policy.retry_attempts) and time.monotonic() < deadline:
        attempt += 1
        try:
            remaining = min(
                policy_timeout,
                max(0.001, deadline - time.monotonic()),
            )
            await engine.backup(str(dest), timeout_seconds=remaining)
            return
        except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError, TimeoutError) as exc:
            last = exc
            leftover = deadline - time.monotonic()
            if leftover <= 0 or attempt >= policy.retry_attempts:
                break
            delay = min(policy.retry_base_delay * (2 ** (attempt - 1)), leftover)
            await asyncio.sleep(max(0.0, delay))
    raise BackupError(f"backup timed out after {attempt} attempts: {last}") from last


def _zip_db(db_path: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(db_path, arcname=ARCHIVE_DB_NAME)


def _promote_sunday_and_rotate(
    catalog: Path,
    daily_path: Path,
    local_when: datetime,
    policy: BackupPolicy,
) -> Path:
    final = daily_path
    if local_when.weekday() == 6:
        weekly_path = catalog / archive_filename("weekly", local_when, policy.tz_label)
        os.replace(daily_path, weekly_path)
        final = weekly_path
    _prune(catalog, "daily_", policy.daily_keep)
    _prune(catalog, "weekly_", policy.weekly_keep)
    return final


def _prune(catalog: Path, prefix: str, keep: int) -> None:
    files = sorted(
        (path for path in catalog.glob(f"{prefix}*.zip") if path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )
    for stale in files[max(0, keep) :]:
        stale.unlink(missing_ok=True)
