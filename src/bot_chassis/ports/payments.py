"""Талоны SKU: порт для кузова и маппинг VoucherRecord → SkuVoucher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ..storage.repositories.transactions import TransactionsRepository


@dataclass(slots=True, frozen=True)
class SkuVoucher:
    voucher_id: str
    bot_id: str
    user_id: int
    sku_code: str
    payment_id: str
    amount: int
    currency: str
    status: str
    redeemed_at: str | None = None


class VoucherManagerPort(Protocol):
    async def get_active_vouchers(
        self,
        bot_id: str,
        user_id: int,
        sku_code: str | None = None,
    ) -> Sequence[SkuVoucher]: ...

    async def redeem_voucher(
        self,
        bot_id: str,
        user_id: int,
        voucher_id: str,
    ) -> tuple[bool, str | None]: ...


class SkuVoucherConsumerPort(Protocol):
    async def on_voucher_issued(self, voucher: SkuVoucher) -> None: ...


class DefaultVoucherManagerAdapter(VoucherManagerPort):
    def __init__(self, tx_repo: TransactionsRepository):
        self._tx = tx_repo

    async def get_active_vouchers(
        self,
        bot_id: str,
        user_id: int,
        sku_code: str | None = None,
    ) -> Sequence[SkuVoucher]:
        records = await self._tx.get_active_vouchers(bot_id, user_id, sku_code=sku_code)
        return [
            SkuVoucher(
                voucher_id=r.voucher_id,
                bot_id=r.bot_id,
                user_id=r.user_id,
                sku_code=r.sku_code,
                payment_id=r.payment_id,
                amount=r.amount,
                currency=r.currency,
                status=r.voucher_status,
                redeemed_at=r.redeemed_at,
            )
            for r in records
        ]

    async def redeem_voucher(
        self,
        bot_id: str,
        user_id: int,
        voucher_id: str,
    ) -> tuple[bool, str | None]:
        return await self._tx.redeem_voucher(bot_id, user_id, voucher_id)
