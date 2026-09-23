"""SQLite engine: one connection per transaction, serialized by an asyncio lock."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

T = TypeVar("T")


def utc_now() -> str:
    """UTC timestamp in SQLite-friendly form (no timezone suffix)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_utc(value: str) -> datetime:
    """Parse timestamps stored by this engine as UTC."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class StorageEngine:
    """Serializes SQLite access. Not a connection pool."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self._db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    async def initialize(self) -> None:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._lock:
            await asyncio.to_thread(self._apply_schema, schema_sql)

    def _apply_schema(self, schema_sql: str) -> None:
        conn = self._connect()
        try:
            # users columns before executescript: idx_users_bot_shbanned
            # references is_shadow_banned, which Stage 1 files do not have yet.
            if _table_exists(conn, "users"):
                _add_column_if_missing(conn, "ALTER TABLE users ADD COLUMN traffic_source TEXT")
                _add_column_if_missing(
                    conn,
                    "ALTER TABLE users ADD COLUMN is_shadow_banned INTEGER NOT NULL DEFAULT 0",
                )
            conn.executescript(schema_sql)
            _rebuild_transactions_if_needed(conn)
            conn.commit()
        finally:
            conn.close()

    async def backup(self, dest_path: str) -> None:
        """Copy the database file. Must not run inside BEGIN IMMEDIATE."""
        async with self._lock:
            await asyncio.to_thread(self._backup_sync, dest_path)

    def _backup_sync(self, dest_path: str) -> None:
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        try:
            target = sqlite3.connect(dest_path)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            return await asyncio.to_thread(self._run_sync, fn)

    def _run_sync(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = fn(conn)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _add_column_if_missing(conn: sqlite3.Connection, sql: str) -> None:
    try:
        conn.execute(sql)
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


_TRANSACTIONS_REBUILD_DDL = """
CREATE TABLE transactions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'telegram_stars',
    payment_id TEXT NOT NULL,
    telegram_payment_charge_id TEXT,
    provider_payment_charge_id TEXT,
    sku_code TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'XTR',
    status TEXT NOT NULL DEFAULT 'paid',
    voucher_id TEXT NOT NULL,
    voucher_status TEXT NOT NULL DEFAULT 'issued',
    redeemed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bot_id, provider, payment_id),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
)
"""


def _rebuild_transactions_if_needed(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "transactions"):
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()}
    if "payment_id" in cols:
        return
    conn.execute("DROP TABLE IF EXISTS transactions_new")
    conn.execute(_TRANSACTIONS_REBUILD_DDL)
    conn.execute(
        """
        INSERT INTO transactions_new (
            id, bot_id, user_id, provider, payment_id, telegram_payment_charge_id,
            provider_payment_charge_id, sku_code, amount, currency, status,
            voucher_id, voucher_status, redeemed_at, created_at, updated_at
        )
        SELECT
            id, bot_id, user_id, 'telegram_stars', telegram_payment_charge_id,
            telegram_payment_charge_id, provider_payment_charge_id, sku_code,
            amount, currency, status, voucher_id, voucher_status, redeemed_at,
            created_at, updated_at
        FROM transactions
        """
    )
    conn.execute("DROP TABLE transactions")
    conn.execute("ALTER TABLE transactions_new RENAME TO transactions")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tx_bot_user ON transactions(bot_id, user_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_voucher ON transactions(bot_id, voucher_id)"
    )
