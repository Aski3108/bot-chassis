"""Гейт pre_checkout, чек Stars и кнопка buy_sku."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from loguru import logger

from ..config import BotChassisConfig
from ..ports.payments import SkuVoucher, SkuVoucherConsumerPort
from ..storage import Storage
from ..storage.repositories.transactions import VoucherRecord
from .service import send_sku_invoice

SHADOW_PAYMENT_ERROR = "Оплата временно недоступна"
PRE_CHECKOUT_INTERNAL_ERROR = "Оплата временно недоступна"
MAINTENANCE_PAYMENT_ERROR = "Сервис временно приостановлен."
PAYLOAD_MISMATCH_ERROR = "Не удалось подтвердить заказ"
BUY_UNAVAILABLE = "Этот товар недоступен"


def create_payments_router(
    bot_id: str,
    storage: Storage,
    config: BotChassisConfig,
    voucher_consumer: SkuVoucherConsumerPort | None = None,
) -> Router:
    router = Router(name="payments")

    @router.callback_query(F.data.startswith("buy_sku:"))
    async def handle_buy_sku(call: CallbackQuery) -> None:
        buyer = call.from_user
        sku_code = (call.data or "").removeprefix("buy_sku:")
        if buyer is None or not sku_code or ":" in sku_code:
            await call.answer()
            return
        sent = False
        try:
            sent = await send_sku_invoice(call.bot, buyer.id, config, sku_code, buyer.id)
        except Exception:
            logger.exception("Не удалось отправить инвойс")
        if not sent:
            await call.answer(BUY_UNAVAILABLE, show_alert=True)
            return
        await call.answer()

    @router.pre_checkout_query()
    async def handle_pre_checkout(query: PreCheckoutQuery) -> None:
        try:
            ok, error = await _pre_checkout_decision(storage, bot_id, query, config)
            await query.answer(ok=ok, error_message=error)
        except Exception:
            logger.exception("Не удалось ответить на pre_checkout")
            try:
                await query.answer(ok=False, error_message=PRE_CHECKOUT_INTERNAL_ERROR)
            except Exception:
                logger.exception("Не удалось отправить fallback-ответ на pre_checkout")

    @router.message(F.successful_payment)
    async def handle_successful_payment(message: Message) -> None:
        payment = message.successful_payment
        if payment is None:
            return
        parsed = _parse_payload(payment.invoice_payload)
        invalid = parsed is None
        if parsed is None:
            payer = message.from_user
            if payer is None:
                logger.error("successful_payment без пользователя и с битым payload")
                await _notify_support(
                    message.bot,
                    config.support_chat_id,
                    f"Битый payload оплаты без пользователя. charge={payment.telegram_payment_charge_id}",
                )
                return
            sku_code, user_id = "invalid_payload", payer.id
        else:
            sku_code, user_id = parsed
        await storage.users.upsert_user(bot_id, user_id)
        record, created = await storage.transactions.record_successful_payment(
            bot_id=bot_id,
            user_id=user_id,
            sku_code=sku_code,
            amount=payment.total_amount,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider="telegram_stars",
            payment_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
            currency=payment.currency,
        )
        if not created:
            return
        if invalid:
            await _notify_support(
                message.bot,
                config.support_chat_id,
                f"Битый payload оплаты. charge={payment.telegram_payment_charge_id}",
            )
            return
        if voucher_consumer is not None:
            try:
                await voucher_consumer.on_voucher_issued(_voucher(record))
            except Exception:
                logger.exception("Потребитель талона не принял оплату")
        if config.notify_on_payment:
            await _notify_support(
                message.bot,
                config.support_chat_id,
                f"Оплата {payment.total_amount} {payment.currency}. sku={sku_code} user_id={user_id} charge={payment.telegram_payment_charge_id}",
            )

    return router


async def _pre_checkout_decision(
    storage: Storage,
    bot_id: str,
    query: PreCheckoutQuery,
    config: BotChassisConfig,
) -> tuple[bool, str | None]:
    maintenance, reason = await storage.bot_settings.get_maintenance_status(bot_id)
    if maintenance:
        return False, reason or MAINTENANCE_PAYMENT_ERROR
    user = query.from_user
    record = await storage.users.get_user(bot_id, user.id) if user is not None else None
    if record is not None and record.is_shadow_banned:
        return False, SHADOW_PAYMENT_ERROR
    parsed = _parse_payload(query.invoice_payload)
    if parsed is None or user is None or parsed[1] != user.id:
        return False, PAYLOAD_MISMATCH_ERROR
    sku_code, _ = parsed
    valid_sku_codes = {sku.sku_code for sku in config.skus}
    if sku_code not in valid_sku_codes or sku_code == "admin_grant":
        return False, PAYLOAD_MISMATCH_ERROR
    return True, None


def _parse_payload(payload: str) -> tuple[str, int] | None:
    try:
        kind, sku_code, user_raw, nonce = payload.split(":")
    except ValueError:
        return None
    if kind != "sku" or not sku_code or not nonce or not user_raw.isdigit():
        return None
    return sku_code, int(user_raw)


def _voucher(record: VoucherRecord) -> SkuVoucher:
    return SkuVoucher(
        voucher_id=record.voucher_id,
        bot_id=record.bot_id,
        user_id=record.user_id,
        sku_code=record.sku_code,
        payment_id=record.payment_id,
        amount=record.amount,
        currency=record.currency,
        status=record.voucher_status,
        redeemed_at=record.redeemed_at,
    )


async def _notify_support(bot, chat_id: int | None, text: str) -> None:
    if chat_id is None:
        return
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        logger.exception("Не удалось отправить уведомление об оплате")
