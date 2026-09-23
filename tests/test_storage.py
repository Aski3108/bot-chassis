"""Тесты контура хранения: bot_id, суперадмины, талоны, подарки. Не трогает SupportThreadStore."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import StorageEngine, utc_now, parse_utc
from bot_chassis.storage.repositories.transactions import TransactionsRepository
from bot_chassis.storage.repositories.users import UsersRepository
from bot_chassis.support_bridge import SupportThreadStore, DEFAULT_SUPPORT_PERSISTENCE_PATH

# DDL Этапа 1: нет payment_id / provider и нет тени. Нужен для проверки пересборки.
_STAGE1_DDL = """
CREATE TABLE IF NOT EXISTS users (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT NOT NULL DEFAULT 'ru',
    is_banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    consent_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_users_bot_banned ON users(bot_id, is_banned);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    telegram_payment_charge_id TEXT NOT NULL,
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
    UNIQUE (bot_id, telegram_payment_charge_id),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tx_bot_user ON transactions(bot_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_voucher ON transactions(bot_id, voucher_id);
"""


class TestStorageContour(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            skus=(SkuItem("audit", "Аудит", "Один раз", 50),),
        )
        self.storage = await create_storage(self.config)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_bot_id_isolation(self) -> None:
        store_b = await create_storage(
            BotChassisConfig(bot_id="bot_b", db_path=self.db_path, superadmin_ids=(200,))
        )
        await self.storage.users.upsert_user("bot_a", 1, username="alice")
        await store_b.users.upsert_user("bot_b", 1, username="bob")
        await self.storage.users.set_ban("bot_a", 1, True, "spam")

        user_a = await self.storage.users.get_user("bot_a", 1)
        user_b = await store_b.users.get_user("bot_b", 1)
        self.assertTrue(user_a.is_banned)
        self.assertFalse(user_b.is_banned)
        self.assertEqual(user_a.username, "alice")
        self.assertEqual(user_b.username, "bob")
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 100, ("superadmin",)))
        self.assertFalse(await self.storage.roles.has_any_role("bot_b", 100, ("superadmin",)))
        self.assertTrue(await store_b.roles.has_any_role("bot_b", 200, ("superadmin",)))

    async def test_upsert_does_not_wipe_ban_or_consent(self) -> None:
        await self.storage.users.upsert_user("bot_a", 5, username="one")
        await self.storage.users.set_ban("bot_a", 5, True, "abuse")
        stamp = utc_now()
        await self.storage.users.set_consent("bot_a", 5, stamp)
        await self.storage.users.upsert_user("bot_a", 5, username="two")
        user = await self.storage.users.get_user("bot_a", 5)
        self.assertEqual(user.username, "two")
        self.assertTrue(user.is_banned)
        self.assertEqual(user.consent_at, stamp)

    async def test_seed_upserts_user_and_empty_ids_warns(self) -> None:
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 100, ("superadmin",)))
        self.assertIsNotNone(await self.storage.users.get_user("bot_a", 100))

        empty = await create_storage(
            BotChassisConfig(bot_id="bot_empty", db_path=self.db_path, superadmin_ids=())
        )
        with patch("bot_chassis.storage.repositories.roles.logger") as mock_log:
            await empty.roles.seed_superadmins("bot_empty", ())
            mock_log.warning.assert_called()

        await self.storage.roles.seed_superadmins("bot_a", (100,))
        self.assertEqual(await self.storage.roles.count_role("bot_a", "superadmin"), 1)

    async def test_cannot_ban_or_revoke_last_superadmin(self) -> None:
        ok, err = await self.storage.users.set_ban("bot_a", 100, True)
        self.assertFalse(ok)
        self.assertEqual(err, "last_superadmin")

        ok, err = await self.storage.roles.revoke_role("bot_a", 100, "superadmin")
        self.assertFalse(ok)
        self.assertEqual(err, "last_superadmin")
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 100, ("superadmin",)))

        await self.storage.roles.grant_role("bot_a", 101, "superadmin", granted_by=100)
        ok, err = await self.storage.roles.revoke_role("bot_a", 101, "superadmin")
        self.assertTrue(ok)
        self.assertIsNone(err)

        await self.storage.roles.grant_role("bot_a", 102, "admin", granted_by=100)
        ok, err = await self.storage.users.set_ban("bot_a", 102, True, "test")
        self.assertTrue(ok)

    async def test_payment_idempotent_and_redeem(self) -> None:
        await self.storage.users.upsert_user("bot_a", 7)
        first, created = await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=7,
            telegram_payment_charge_id="chg-1",
            sku_code="audit",
            amount=50,
        )
        self.assertTrue(created)
        self.assertEqual(first.voucher_status, "issued")
        self.assertEqual(first.provider, "telegram_stars")
        self.assertEqual(first.payment_id, "chg-1")
        self.assertEqual(first.telegram_payment_charge_id, "chg-1")
        self.assertIsNone(first.redeemed_at)
        self.assertIsInstance(first.amount, int)

        second, created_again = await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=7,
            telegram_payment_charge_id="chg-1",
            sku_code="audit",
            amount=50,
        )
        self.assertFalse(created_again)
        self.assertEqual(first.voucher_id, second.voucher_id)

        active = await self.storage.transactions.get_active_vouchers("bot_a", 7, "audit")
        self.assertEqual(len(active), 1)

        ok, err = await self.storage.transactions.redeem_voucher("bot_a", 7, first.voucher_id)
        self.assertTrue(ok)
        self.assertIsNone(err)
        redeemed = await _transaction_row(self.storage.engine, "bot_a", "chg-1")
        self.assertEqual(redeemed["voucher_status"], "redeemed")
        self.assertIsNotNone(redeemed["redeemed_at"])
        ok, err = await self.storage.transactions.redeem_voucher("bot_a", 7, first.voucher_id)
        self.assertFalse(ok)
        self.assertEqual(err, "already_redeemed")
        self.assertEqual(len(await self.storage.transactions.get_active_vouchers("bot_a", 7)), 0)

    async def test_gift_invariants(self) -> None:
        ok, err = await self.storage.subscriptions.grant_gift_access(
            "bot_a", 50, granted_by=100, days=None
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIsNotNone(await self.storage.users.get_user("bot_a", 50))
        self.assertTrue(await self.storage.subscriptions.has_active_access("bot_a", 50))

        first = await self.storage.subscriptions.get_active_subscription("bot_a", 50)
        self.assertTrue(first.is_lifetime)
        self.assertIsNone(first.expires_at)

        ok, err = await self.storage.subscriptions.grant_gift_access(
            "bot_a", 50, granted_by=100, days=30
        )
        self.assertTrue(ok)
        second = await self.storage.subscriptions.get_active_subscription("bot_a", 50)
        self.assertFalse(second.is_lifetime)
        self.assertIsNotNone(second.expires_at)
        self.assertNotEqual(first.id, second.id)
        self.assertTrue(await self.storage.subscriptions.has_active_access("bot_a", 50))

        ok, err = await self.storage.subscriptions.revoke_gift_access("bot_a", 50)
        self.assertTrue(ok)
        self.assertFalse(await self.storage.subscriptions.has_active_access("bot_a", 50))

        await self.storage.users.set_ban("bot_a", 50, True, "x")
        ok, err = await self.storage.subscriptions.grant_gift_access(
            "bot_a", 50, granted_by=100, days=0
        )
        self.assertTrue(ok)
        self.assertTrue(await self.storage.subscriptions.has_active_access("bot_a", 50))

        ok, err = await self.storage.subscriptions.grant_gift_access(
            "bot_a", 51, granted_by=100, days=-1
        )
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_days")

    async def test_gift_expiry_is_lazy(self) -> None:
        await self.storage.subscriptions.grant_gift_access(
            "bot_a", 60, granted_by=100, days=30
        )
        past = (parse_utc(utc_now()) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        def _expire(conn) -> None:
            conn.execute(
                """
                UPDATE subscriptions SET expires_at = ?
                WHERE bot_id = ? AND user_id = ? AND status = 'active'
                """,
                (past, "bot_a", 60),
            )

        await self.storage.engine.run(_expire)
        self.assertFalse(await self.storage.subscriptions.has_active_access("bot_a", 60))

    async def test_support_threads_repo_does_not_touch_json_store(self) -> None:
        await self.storage.users.upsert_user("bot_a", 9)
        await self.storage.support_threads.register_thread("bot_a", -100, 1, 9)
        await self.storage.support_threads.register_thread("bot_a", -100, 2, 9)
        self.assertEqual(await self.storage.support_threads.resolve_user("bot_a", -100, 1), 9)
        self.assertIsNone(await self.storage.support_threads.resolve_user("bot_b", -100, 1))
        changed = await self.storage.support_threads.mark_answered("bot_a", 9)
        self.assertEqual(changed, 2)
        self.assertEqual(DEFAULT_SUPPORT_PERSISTENCE_PATH, os.path.join("temp", "support_threads.json"))
        store = SupportThreadStore(persistence_file=None)
        self.assertIsNone(store.resolve_user(chat_id=-100, reply_to_message_id=1))

    async def test_maintenance_flag_is_per_bot(self) -> None:
        await self.storage.bot_settings.set_maintenance_status(
            "bot_a", True, reason="pause", updated_by=100
        )
        on, reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertTrue(on)
        self.assertEqual(reason, "pause")
        off, other = await self.storage.bot_settings.get_maintenance_status("bot_b")
        self.assertFalse(off)
        self.assertIsNone(other)

    async def test_upsert_does_not_overwrite_language(self) -> None:
        created = await self.storage.users.upsert_user("bot_a", 8, language_code="en")
        self.assertEqual(created.language_code, "en")
        self.assertTrue(created.created_at)
        self.assertTrue(await self.storage.users.set_language_code("bot_a", 8, "de"))
        await self.storage.users.upsert_user("bot_a", 8, username="renamed", language_code="fr")
        user = await self.storage.users.get_user("bot_a", 8)
        self.assertEqual(user.language_code, "de")
        self.assertEqual(user.username, "renamed")
        self.assertFalse(await self.storage.users.set_language_code("bot_a", 404, "en"))

    async def test_traffic_source_is_first_touch(self) -> None:
        self.assertFalse(await self.storage.users.set_traffic_source("bot_a", 404, "ads"))
        await self.storage.users.upsert_user("bot_a", 21)
        self.assertTrue(await self.storage.users.set_traffic_source("bot_a", 21, "utm_a"))
        self.assertTrue(await self.storage.users.set_traffic_source("bot_a", 21, "utm_b"))
        user = await self.storage.users.get_user("bot_a", 21)
        self.assertEqual(user.traffic_source, "utm_a")

    async def test_shadow_ban_and_broadcast_ids(self) -> None:
        ok, err = await self.storage.users.set_shadow_ban("bot_a", 404, True)
        self.assertFalse(ok)
        self.assertEqual(err, "not_found")

        ok, err = await self.storage.users.set_shadow_ban("bot_a", 100, True)
        self.assertFalse(ok)
        self.assertEqual(err, "target_is_admin")
        superadmin = await self.storage.users.get_user("bot_a", 100)
        self.assertFalse(superadmin.is_shadow_banned)

        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        ok, err = await self.storage.users.set_shadow_ban("bot_a", 14, True)
        self.assertFalse(ok)
        self.assertEqual(err, "target_is_admin")
        ok, err = await self.storage.users.set_shadow_ban("bot_a", 14, False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        await self.storage.users.upsert_user("bot_a", 11)
        await self.storage.users.upsert_user("bot_a", 12)
        await self.storage.users.upsert_user("bot_a", 13)
        await self.storage.users.set_ban("bot_a", 12, True, "spam")
        ok, err = await self.storage.users.set_shadow_ban("bot_a", 13, True)
        self.assertTrue(ok)
        self.assertIsNone(err)
        shadowed = await self.storage.users.get_user("bot_a", 13)
        self.assertTrue(shadowed.is_shadow_banned)

        ids = await self.storage.users.get_broadcast_user_ids("bot_a")
        self.assertIn(11, ids)
        self.assertIn(100, ids)
        self.assertNotIn(12, ids)
        self.assertNotIn(13, ids)

    async def test_referrals(self) -> None:
        ok, err = await self.storage.referrals.record_referral("bot_a", 30, 30)
        self.assertFalse(ok)
        self.assertEqual(err, "self_referral")

        ok, err = await self.storage.referrals.record_referral("bot_a", 30, 31)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIsNotNone(await self.storage.users.get_user("bot_a", 30))
        self.assertIsNotNone(await self.storage.users.get_user("bot_a", 31))

        ok, err = await self.storage.referrals.record_referral("bot_a", 30, 31)
        self.assertFalse(ok)
        self.assertEqual(err, "already_exists")
        self.assertEqual(await self.storage.referrals.get_referrals_count("bot_a", 30), 1)

        ok, err = await self.storage.referrals.record_referral("bot_a", 30, 32)
        self.assertTrue(ok)
        self.assertEqual(await self.storage.referrals.get_referrals_count("bot_a", 30), 2)

        self.assertTrue(await self.storage.referrals.mark_referral_rewarded("bot_a", 31))
        self.assertFalse(await self.storage.referrals.mark_referral_rewarded("bot_a", 99))

        def _rewarded(conn):
            return conn.execute(
                "SELECT rewarded FROM referrals WHERE bot_id = ? AND referee_id = ?",
                ("bot_a", 31),
            ).fetchone()

        row = await self.storage.engine.run(_rewarded)
        self.assertEqual(int(row["rewarded"]), 1)

    async def test_mark_refunded(self) -> None:
        await self.storage.users.upsert_user("bot_a", 40)
        ok, err = await self.storage.transactions.mark_refunded("bot_a", "missing")
        self.assertFalse(ok)
        self.assertEqual(err, "not_found")

        paid, created = await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=40,
            sku_code="audit",
            amount=50,
            telegram_payment_charge_id="chg-stars",
            payment_id="pay-stars",
        )
        self.assertTrue(created)
        self.assertEqual(paid.provider, "telegram_stars")
        self.assertEqual(paid.payment_id, "pay-stars")

        ok, err = await self.storage.transactions.mark_refunded("bot_a", "pay-stars")
        self.assertTrue(ok)
        self.assertIsNone(err)
        row = await _transaction_row(self.storage.engine, "bot_a", "pay-stars")
        self.assertEqual(row["status"], "refunded")
        self.assertEqual(row["voucher_status"], "cancelled")

        ok, err = await self.storage.transactions.mark_refunded("bot_a", "pay-stars")
        self.assertFalse(ok)
        self.assertEqual(err, "already_refunded")

        grant, created = await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=40,
            sku_code="audit",
            amount=0,
            telegram_payment_charge_id="grant-1",
            provider="admin_grant",
            payment_id="grant-1",
        )
        self.assertTrue(created)
        ok, err = await self.storage.transactions.mark_refunded(
            "bot_a", "grant-1", provider="admin_grant"
        )
        self.assertFalse(ok)
        self.assertEqual(err, "not_stars")
        grant_row = await _transaction_row(
            self.storage.engine, "bot_a", "grant-1", provider="admin_grant"
        )
        self.assertEqual(grant_row["status"], "paid")
        self.assertEqual(grant_row["voucher_status"], "issued")

        used, created = await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=40,
            sku_code="audit",
            amount=50,
            telegram_payment_charge_id="chg-used",
            payment_id="pay-used",
        )
        self.assertTrue(created)
        ok, err = await self.storage.transactions.redeem_voucher("bot_a", 40, used.voucher_id)
        self.assertTrue(ok)
        ok, err = await self.storage.transactions.mark_refunded("bot_a", "pay-used")
        self.assertTrue(ok)
        self.assertIsNone(err)
        used_row = await _transaction_row(self.storage.engine, "bot_a", "pay-used")
        self.assertEqual(used_row["status"], "refunded")
        self.assertEqual(used_row["voucher_status"], "cancelled")
        self.assertIsNotNone(used_row["redeemed_at"])

    async def test_migrate_stage1_schema(self) -> None:
        legacy_path = os.path.join(self._tmp.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        try:
            conn.executescript(_STAGE1_DDL)
            conn.execute(
                "INSERT INTO users (bot_id, user_id, language_code) VALUES ('bot_a', 7, 'en')"
            )
            conn.execute(
                """
                INSERT INTO transactions (
                    bot_id, user_id, telegram_payment_charge_id, sku_code, amount,
                    currency, status, voucher_id, voucher_status
                ) VALUES ('bot_a', 7, 'chg-old', 'audit', 50, 'XTR', 'paid', 'v-old', 'issued')
                """
            )
            conn.commit()
        finally:
            conn.close()

        engine = StorageEngine(legacy_path)
        await engine.initialize()
        await engine.initialize()

        def _inspect(conn):
            user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            tx_info = list(conn.execute("PRAGMA table_info(transactions)").fetchall())
            tx_cols = {row[1]: row[2] for row in tx_info}
            index = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'index' AND name = 'idx_users_bot_shbanned'
                """
            ).fetchone()
            tx = conn.execute(
                """
                SELECT provider, payment_id, telegram_payment_charge_id, amount
                FROM transactions
                WHERE voucher_id = 'v-old'
                """
            ).fetchone()
            return user_cols, tx_cols, index, tx

        user_cols, tx_cols, index, tx = await engine.run(_inspect)
        self.assertIn("traffic_source", user_cols)
        self.assertIn("is_shadow_banned", user_cols)
        self.assertIsNotNone(index)
        self.assertIn("payment_id", tx_cols)
        self.assertEqual(tx_cols["amount"].upper(), "INTEGER")
        self.assertEqual(tx["provider"], "telegram_stars")
        self.assertEqual(tx["payment_id"], "chg-old")
        self.assertEqual(tx["telegram_payment_charge_id"], "chg-old")
        self.assertEqual(int(tx["amount"]), 50)

        user = await UsersRepository(engine).get_user("bot_a", 7)
        self.assertEqual(user.language_code, "en")
        self.assertFalse(user.is_shadow_banned)
        self.assertIsNone(user.traffic_source)
        self.assertTrue(user.created_at)

        record, created = await TransactionsRepository(engine).record_successful_payment(
            bot_id="bot_a",
            user_id=7,
            sku_code="audit",
            amount=50,
            telegram_payment_charge_id="chg-old",
        )
        self.assertFalse(created)
        self.assertEqual(record.voucher_id, "v-old")
        self.assertEqual(record.payment_id, "chg-old")

    async def test_backup_keeps_source_readable(self) -> None:
        await self.storage.users.upsert_user("bot_a", 42, username="backup_user")
        dest = os.path.join(self._tmp.name, "backup.db")
        await self.storage.engine.backup(dest)
        conn = sqlite3.connect(dest)
        try:
            row = conn.execute(
                "SELECT username FROM users WHERE bot_id = ? AND user_id = ?",
                ("bot_a", 42),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "backup_user")
        still = await self.storage.users.get_user("bot_a", 42)
        self.assertEqual(still.username, "backup_user")


def _transaction_row(engine, bot_id: str, payment_id: str, provider: str = "telegram_stars"):
    async def _read():
        def _op(conn):
            return conn.execute(
                """
                SELECT * FROM transactions
                WHERE bot_id = ? AND provider = ? AND payment_id = ?
                """,
                (bot_id, provider, payment_id),
            ).fetchone()

        return await engine.run(_op)

    return _read()


if __name__ == "__main__":
    unittest.main()
