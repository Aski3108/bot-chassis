"""Конфиг полной рамы (доступен с этапа Storage, без I/O)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SkuItem:
    sku_code: str
    title: str
    description: str
    stars_price: int
    issues_voucher: bool = True


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
    welcome_text: str | None = None  # HTML, как меню /start; None — текст шасси
    origin_bot_id: str | None = None


def resolved_origin(config: BotChassisConfig) -> str:
    return config.origin_bot_id or config.bot_id


def resolved_alert_chat_id(config: BotChassisConfig) -> int | None:
    """Prefer the audit chat and preserve support as a compatibility fallback."""
    return config.audit_chat_id or config.support_chat_id
