"""Внешний каталог донатов. Суммы задаёт кузов, рама их не зашивает."""

from __future__ import annotations

from typing import Protocol, Sequence

from ..config import BotChassisConfig, SkuItem


class DonationCatalogPort(Protocol):
    def list_donations(self) -> Sequence[SkuItem]:
        """SKU без ваучера. Пустой список скрывает кнопку «Поддержать проект»."""


def resolve_donation_items(
    config: BotChassisConfig,
    donation_catalog: DonationCatalogPort | Sequence[SkuItem] | None = None,
) -> tuple[SkuItem, ...]:
    if donation_catalog is None:
        return tuple(sku for sku in config.skus if not sku.issues_voucher)
    listed = donation_catalog.list_donations() if hasattr(donation_catalog, "list_donations") else donation_catalog
    items = tuple(listed)
    if any(item.issues_voucher for item in items):
        raise ValueError("donation_catalog accepts only SKU with issues_voucher=False")
    codes = [item.sku_code for item in items]
    if len(codes) != len(set(codes)):
        raise ValueError("donation_catalog contains duplicate sku_code")
    return items


def merge_payment_skus(
    configured: Sequence[SkuItem],
    donations: Sequence[SkuItem],
) -> tuple[SkuItem, ...]:
    """Один каталог для кнопки, invoice, pre-checkout и записи платежа."""
    donation_by_code = {item.sku_code: item for item in donations}
    merged = [donation_by_code.pop(item.sku_code, item) for item in configured]
    merged.extend(donation_by_code.values())
    return tuple(merged)
