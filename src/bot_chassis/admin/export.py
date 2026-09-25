"""Выгрузка базы бота в CSV (utf-8-sig) и ZIP. Только строки этого bot_id."""

from __future__ import annotations

import csv
import io
import zipfile

from ..storage import Storage

EXPORT_SCOPES = frozenset({"users", "payments", "gifts", "all"})

_USERS_SQL = """
SELECT user_id, username, first_name, last_name, language_code,
       is_banned, ban_reason, is_shadow_banned, consent_at, traffic_source,
       created_at, updated_at
FROM users
WHERE bot_id = ?
ORDER BY user_id
"""
_PAYMENTS_SQL = """
SELECT id, user_id, provider, payment_id, telegram_payment_charge_id,
       merchant_origin_bot_id, merchant_telegram_bot_id,
       sku_code, amount, currency, status, voucher_id, voucher_status,
       redeemed_at, created_at
FROM transactions
WHERE bot_id = ?
ORDER BY id
"""
_GIFTS_SQL = """
SELECT id, user_id, plan_code, is_lifetime, expires_at, granted_by,
       grant_reason, status, created_at, updated_at
FROM subscriptions
WHERE bot_id = ?
ORDER BY id
"""


async def build_export(storage: Storage, bot_id: str, scope: str) -> tuple[bytes, str]:
    if scope not in EXPORT_SCOPES:
        raise ValueError(scope)
    tables = {
        "users": await _table_csv(storage, _USERS_SQL, bot_id),
        "payments": await _table_csv(storage, _PAYMENTS_SQL, bot_id),
        "gifts": await _table_csv(storage, _GIFTS_SQL, bot_id),
    }
    if scope != "all":
        return tables[scope], f"{scope}.csv"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("users", "payments", "gifts"):
            archive.writestr(f"{name}.csv", tables[name])
    return buffer.getvalue(), "export.zip"


async def _table_csv(storage: Storage, sql: str, bot_id: str) -> bytes:
    def _op(conn) -> bytes:
        cursor = conn.execute(sql, (bot_id,))
        headers = [item[0] for item in cursor.description]
        text = io.StringIO()
        writer = csv.writer(text, lineterminator="\n")
        writer.writerow(headers)
        while True:
            batch = cursor.fetchmany(1000)
            if not batch:
                break
            for row in batch:
                writer.writerow("" if value is None else value for value in row)
        return text.getvalue().encode("utf-8-sig")

    return await storage.engine.run(_op)
