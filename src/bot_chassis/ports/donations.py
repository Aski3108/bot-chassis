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
    return tuple(listed)
