"""Конфиг полной рамы (доступен с этапа Storage, без I/O)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SkuItem:
    sku_code: str
    title: str
    description: str
    stars_price: int


@dataclass(slots=True, frozen=True)
class BotChassisConfig:
    bot_id: str
    enable_buttons: bool = True
    enable_admin: bool = True
    enable_payments: bool = True
    db_path: str = "bot_chassis.db"
    superadmin_ids: tuple[int, ...] = ()
    skus: tuple[SkuItem, ...] = ()
    support_chat_id: int | None = None
    audit_chat_id: int | None = None
    default_locale: str = "ru"
    enable_error_alerts: bool = True
    enable_throttling: bool = True
    notify_on_payment: bool = True
    enable_language_switch: bool = False
    enable_referrals: bool = False
