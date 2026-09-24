"""Сборка и отправка инвойса Telegram Stars."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from aiogram.types import LabeledPrice

from ..config import BotChassisConfig

_PAYLOAD_LIMIT = 128


class InvoiceError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(slots=True, frozen=True)
class StarInvoice:
    title: str
    description: str
    payload: str
    currency: str
    provider_token: str
    prices: tuple[LabeledPrice, ...]
    is_flexible: bool


def build_star_invoice(config: BotChassisConfig, sku_code: str, user_id: int) -> StarInvoice:
    if sku_code == "admin_grant":
        raise InvoiceError("admin_grant")
    sku = next((item for item in config.skus if item.sku_code == sku_code), None)
    if sku is None:
        raise InvoiceError("unknown_sku")
    if sku.stars_price < 1:
        raise InvoiceError("invalid_price")
    nonce = uuid.uuid4().hex[:8]
    payload = f"sku:{sku.sku_code}:{user_id}:{nonce}"
    if len(payload.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise InvoiceError("payload_too_long")
    return StarInvoice(
        title=sku.title,
        description=sku.description,
        payload=payload,
        currency="XTR",
        provider_token="",
        prices=(LabeledPrice(label=sku.title, amount=sku.stars_price),),
        is_flexible=False,
    )


async def send_sku_invoice(bot, chat_id: int, config: BotChassisConfig, sku_code: str, user_id: int) -> bool:
    try:
        invoice = build_star_invoice(config, sku_code, user_id)
    except InvoiceError:
        return False
    await bot.send_invoice(
        chat_id=chat_id,
        title=invoice.title,
        description=invoice.description,
        payload=invoice.payload,
        currency=invoice.currency,
        prices=list(invoice.prices),
        provider_token=invoice.provider_token,
        is_flexible=invoice.is_flexible,
    )
    return True
