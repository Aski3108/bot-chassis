"""Чеки Stars: идемпотентность по (bot_id, provider, payment_id), погашение и рефанд."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional, Sequence

from ..engine import StorageEngine, utc_now


@dataclass(slots=True, frozen=True)
class VoucherRecord:
    voucher_id: str
    bot_id: str
    user_id: int
    sku_code: str
    telegram_payment_charge_id: str
    amount: int
    currency: str
    status: str
    voucher_status: str
    provider: str
    payment_id: str
    redeemed_at: Optional[str] = None


def _row_to_voucher(row) -> VoucherRecord:
    return VoucherRecord(
        voucher_id=row["voucher_id"],
        bot_id=row["bot_id"],
        user_id=int(row["user_id"]),
        sku_code=row["sku_code"],
        telegram_payment_charge_id=row["telegram_payment_charge_id"],
        amount=int(row["amount"]),
        currency=row["currency"],
        status=row["status"],
        voucher_status=row["voucher_status"],
        provider=row["provider"],
        payment_id=row["payment_id"],
        redeemed_at=row["redeemed_at"],
    )


class TransactionsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def record_successful_payment(
        self,
        bot_id: str,
        user_id: int,
        sku_code: str,
        amount: int,
        telegram_payment_charge_id: str,
        provider: str = "telegram_stars",
        payment_id: Optional[str] = None,
        provider_payment_charge_id: Optional[str] = None,
        currency: str = "XTR",
        voucher_id: Optional[str] = None,
    ) -> tuple[VoucherRecord, bool]:
        """
        Insert paid+issued voucher. Repeat (bot_id, provider, payment_id) returns the existing row.
        Second value is True iff this call created the row.
        """
        resolved_payment_id = telegram_payment_charge_id if payment_id is None else payment_id
        new_voucher_id = voucher_id or str(uuid.uuid4())

        def _op(conn) -> tuple[VoucherRecord, bool]:
            existing = conn.execute(
                """
                SELECT * FROM transactions
                WHERE bot_id = ? AND provider = ? AND payment_id = ?
                """,
                (bot_id, provider, resolved_payment_id),
            ).fetchone()
            if existing:
                return _row_to_voucher(existing), False
            conn.execute(
                """
                INSERT INTO transactions (
                    bot_id, user_id, provider, payment_id, telegram_payment_charge_id,
                    provider_payment_charge_id, sku_code, amount, currency, status,
                    voucher_id, voucher_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'paid', ?, 'issued', ?)
                """,
                (
                    bot_id,
                    user_id,
                    provider,
                    resolved_payment_id,
                    telegram_payment_charge_id,
                    provider_payment_charge_id,
                    sku_code,
                    amount,
                    currency,
                    new_voucher_id,
                    utc_now(),
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM transactions
                WHERE bot_id = ? AND provider = ? AND payment_id = ?
                """,
                (bot_id, provider, resolved_payment_id),
            ).fetchone()
            return _row_to_voucher(row), True

        return await self._engine.run(_op)

    async def mark_refunded(
        self,
        bot_id: str,
        payment_id: str,
        provider: str = "telegram_stars",
    ) -> tuple[bool, Optional[str]]:
        def _op(conn) -> tuple[bool, Optional[str]]:
            row = conn.execute(
                """
                SELECT status, voucher_status, provider
                FROM transactions
                WHERE bot_id = ? AND provider = ? AND payment_id = ?
                """,
                (bot_id, provider, payment_id),
            ).fetchone()
            if not row:
                return False, "not_found"
            if row["provider"] != "telegram_stars":
                return False, "not_stars"
            if row["status"] == "refunded" or row["voucher_status"] == "cancelled":
                return False, "already_refunded"
            conn.execute(
                """
                UPDATE transactions
                SET status = 'refunded', voucher_status = 'cancelled', updated_at = ?
                WHERE bot_id = ? AND provider = ? AND payment_id = ?
                """,
                (utc_now(), bot_id, provider, payment_id),
            )
            return True, None

        return await self._engine.run(_op)

    async def get_active_vouchers(
        self,
        bot_id: str,
        user_id: int,
        sku_code: Optional[str] = None,
    ) -> Sequence[VoucherRecord]:
        def _op(conn) -> list[VoucherRecord]:
            if sku_code is None:
                rows = conn.execute(
                    """
                    SELECT * FROM transactions
                    WHERE bot_id = ? AND user_id = ? AND voucher_status = 'issued'
                    ORDER BY id ASC
                    """,
                    (bot_id, user_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM transactions
                    WHERE bot_id = ? AND user_id = ? AND sku_code = ? AND voucher_status = 'issued'
                    ORDER BY id ASC
                    """,
                    (bot_id, user_id, sku_code),
                ).fetchall()
            return [_row_to_voucher(row) for row in rows]

        return await self._engine.run(_op)

    async def redeem_voucher(
        self,
        bot_id: str,
        user_id: int,
        voucher_id: str,
    ) -> tuple[bool, Optional[str]]:
        now = utc_now()

        def _op(conn) -> tuple[bool, Optional[str]]:
            cur = conn.execute(
                """
                UPDATE transactions
                SET voucher_status = 'redeemed', redeemed_at = ?, updated_at = ?
                WHERE bot_id = ? AND user_id = ? AND voucher_id = ? AND voucher_status = 'issued'
                """,
                (now, now, bot_id, user_id, voucher_id),
            )
            if cur.rowcount > 0:
                return True, None
            row = conn.execute(
                """
                SELECT voucher_status FROM transactions
                WHERE bot_id = ? AND user_id = ? AND voucher_id = ?
                """,
                (bot_id, user_id, voucher_id),
            ).fetchone()
            if not row:
                return False, "not_found"
            return False, "already_redeemed"

        return await self._engine.run(_op)
