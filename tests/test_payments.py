"""Инвойс Telegram Stars, гейт предоплаты и чек."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.payments import (
    BUY_UNAVAILABLE,
    MAINTENANCE_PAYMENT_ERROR,
    PAYLOAD_MISMATCH_ERROR,
    PRE_CHECKOUT_INTERNAL_ERROR,
    SHADOW_PAYMENT_ERROR,
    InvoiceError,
    build_star_invoice,
    create_payments_router,
)
from bot_chassis.storage import create_storage


def _config(*skus: SkuItem) -> BotChassisConfig:
    return BotChassisConfig(bot_id="bot_a", skus=skus)


class TestStarInvoice(unittest.TestCase):
    def test_builds_xtr_invoice_without_scaling_price(self) -> None:
        sku = SkuItem(sku_code="vip", title="VIP", description="Месяц", stars_price=150)
        invoice = build_star_invoice(_config(sku), "vip", 42)
        self.assertEqual(invoice.currency, "XTR")
        self.assertEqual(invoice.provider_token, "")
        self.assertFalse(invoice.is_flexible)
        self.assertEqual(invoice.title, "VIP")
        self.assertEqual(invoice.description, "Месяц")
        self.assertEqual(len(invoice.prices), 1)
        self.assertEqual(invoice.prices[0].label, "VIP")
        self.assertEqual(invoice.prices[0].amount, 150)
        self.assertRegex(invoice.payload, r"^sku:vip:42:[0-9a-f]{8}$")
        self.assertLessEqual(len(invoice.payload.encode("utf-8")), 128)
        other = build_star_invoice(_config(sku), "vip", 42)
        self.assertNotEqual(invoice.payload, other.payload)

    def test_rejects_unknown_admin_grant_and_long_payload(self) -> None:
        sku = SkuItem(sku_code="vip", title="VIP", description="Месяц", stars_price=1)
        grant = SkuItem(sku_code="admin_grant", title="Grant", description="x", stars_price=1)
        config = _config(sku, grant)
        with self.assertRaises(InvoiceError) as unknown:
            build_star_invoice(config, "missing", 1)
        self.assertEqual(unknown.exception.reason, "unknown_sku")
        with self.assertRaises(InvoiceError) as blocked:
            build_star_invoice(config, "admin_grant", 1)
        self.assertEqual(blocked.exception.reason, "admin_grant")
        huge = SkuItem(sku_code="s" * 120, title="T", description="D", stars_price=1)
        with self.assertRaises(InvoiceError) as too_long:
            build_star_invoice(_config(huge), "s" * 120, 1)
        self.assertEqual(too_long.exception.reason, "payload_too_long")
        free = SkuItem(sku_code="free", title="F", description="D", stars_price=0)
        with self.assertRaises(InvoiceError) as price:
            build_star_invoice(_config(free), "free", 1)
        self.assertEqual(price.exception.reason, "invalid_price")


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        if method.__class__.__name__ == "SendMessage":
            return Message(
                message_id=50,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestPaymentGate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.consumer = AsyncMock()
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=os.path.join(self._tmp.name, "chassis.db"),
            support_chat_id=-100,
            skus=(
                SkuItem(sku_code="vip", title="VIP", description="Месяц", stars_price=150),
                SkuItem(sku_code="admin_grant", title="Grant", description="x", stars_price=1),
            ),
        )
        self.storage = await create_storage(self.config)
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.dp = Dispatcher()
        self.dp.include_router(create_payments_router("bot_a", self.storage, self.config, self.consumer))
        self._update_id = 1

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def test_pre_checkout_does_not_use_work_gate(self) -> None:
        await self.storage.users.upsert_user("bot_a", 7)
        await self.storage.users.set_ban("bot_a", 7, True, "spam")
        with patch("bot_chassis.ports.work_gate.DefaultWorkGateAdapter.can_accept_work", new_callable=AsyncMock) as gate:
            await self._pre_checkout(7, "sku:vip:7:abcd")
            gate.assert_not_called()
        answer = self._answers()[0]
        self.assertTrue(answer.ok)
        self.assertIsNone(answer.error_message)

        self.session.requests.clear()
        await self.storage.users.set_shadow_ban("bot_a", 7, True)
        await self._pre_checkout(7, "sku:vip:7:abcd")
        shadow = self._answers()[0]
        self.assertFalse(shadow.ok)
        self.assertEqual(shadow.error_message, SHADOW_PAYMENT_ERROR)
        self.assertNotIn("бан", shadow.error_message.lower())

        self.session.requests.clear()
        await self.storage.bot_settings.set_maintenance_status("bot_a", True, reason="пауза", updated_by=1)
        await self._pre_checkout(7, "sku:vip:7:abcd")
        self.assertEqual(self._answers()[0].error_message, "пауза")

        self.session.requests.clear()
        await self.storage.bot_settings.set_maintenance_status("bot_a", True, reason=None, updated_by=1)
        await self._pre_checkout(7, "sku:vip:7:abcd")
        self.assertEqual(self._answers()[0].error_message, MAINTENANCE_PAYMENT_ERROR)

        self.session.requests.clear()
        await self.storage.bot_settings.set_maintenance_status("bot_a", False, reason=None, updated_by=1)
        await self.storage.users.set_shadow_ban("bot_a", 7, False)
        await self._pre_checkout(7, "sku:vip:99:abcd")
        self.assertEqual(self._answers()[0].error_message, PAYLOAD_MISMATCH_ERROR)
        await self._pre_checkout(7, "broken")
        self.assertEqual(self._answers()[1].error_message, PAYLOAD_MISMATCH_ERROR)

        self.session.requests.clear()
        await self._pre_checkout(7, "sku:unknown_item:7:abcd")
        self.assertFalse(self._answers()[0].ok)
        self.assertEqual(self._answers()[0].error_message, PAYLOAD_MISMATCH_ERROR)
        await self._pre_checkout(7, "sku:admin_grant:7:abcd")
        self.assertFalse(self._answers()[1].ok)
        self.assertEqual(self._answers()[1].error_message, PAYLOAD_MISMATCH_ERROR)

    async def test_successful_payment_records_once_and_alerts(self) -> None:
        await self.storage.bot_settings.set_maintenance_status("bot_a", True, reason="пауза", updated_by=1)
        await self.storage.users.upsert_user("bot_a", 7)
        await self.storage.users.set_shadow_ban("bot_a", 7, True)
        await self._paid(7, "sku:vip:7:abcd", "chg-1", 150)
        row = await self._tx("chg-1")
        self.assertEqual(row, ("vip", 150, "telegram_stars", "paid"))
        self.consumer.on_voucher_issued.assert_awaited_once()
        voucher = self.consumer.on_voucher_issued.await_args.args[0]
        self.assertEqual(voucher.sku_code, "vip")
        self.assertEqual(voucher.amount, 150)
        self.assertEqual(voucher.payment_id, "chg-1")
        alerts = [item.text for item in self._named("SendMessage") if item.chat_id == -100]
        self.assertTrue(any("sku=vip" in item and "charge=chg-1" in item for item in alerts))

        self.consumer.reset_mock()
        self.session.requests.clear()
        await self._paid(7, "sku:vip:7:abcd", "chg-1", 150)
        self.consumer.on_voucher_issued.assert_not_awaited()
        self.assertFalse(self._named("SendMessage"))
        self.assertEqual(await self._tx_count("chg-1"), 1)

        self.session.requests.clear()
        await self._paid(7, "broken", "chg-bad", 10)
        bad = await self._tx("chg-bad")
        self.assertEqual(bad[0], "invalid_payload")
        self.consumer.on_voucher_issued.assert_not_awaited()
        self.assertTrue(any("Битый payload" in item.text for item in self._named("SendMessage")))

    async def test_network_payment_records_actual_merchant_and_donate_has_no_voucher(self) -> None:
        network_config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.config.db_path,
            support_chat_id=-100,
            audit_chat_id=-200,
            origin_bot_id="bpd",
            skus=(
                SkuItem("donate_50", "Поддержать", "Донат", 50, issues_voucher=False),
            ),
        )
        self.dp = Dispatcher()
        self.dp.include_router(
            create_payments_router("bot_a", self.storage, network_config, self.consumer)
        )

        await self._paid(7, "sku:donate_50:7:abcd", "chg-donate", 50)

        def _op(conn):
            return conn.execute(
                """
                SELECT merchant_origin_bot_id, merchant_telegram_bot_id,
                       voucher_status, redeemed_at
                FROM transactions
                WHERE bot_id = ? AND payment_id = ?
                """,
                ("bot_a", "chg-donate"),
            ).fetchone()

        row = await self.storage.engine.run(_op)
        self.assertEqual(row["merchant_origin_bot_id"], "bpd")
        self.assertEqual(int(row["merchant_telegram_bot_id"]), self.bot.id)
        self.assertEqual(row["voucher_status"], "redeemed")
        self.assertIsNotNone(row["redeemed_at"])
        self.consumer.on_voucher_issued.assert_not_awaited()
        alerts = self._named("SendMessage")
        self.assertTrue(any(item.chat_id == -200 and "sku=donate_50" in item.text for item in alerts))
        self.assertFalse(any(item.chat_id == -100 for item in alerts))

    async def test_pre_checkout_answers_false_on_internal_error(self) -> None:
        with patch(
            "bot_chassis.payments.router._pre_checkout_decision",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            await self._pre_checkout(7, "sku:vip:7:abcd")
        answers = self._answers()
        self.assertEqual(len(answers), 1)
        self.assertFalse(answers[0].ok)
        self.assertEqual(answers[0].error_message, PRE_CHECKOUT_INTERNAL_ERROR)

    async def test_broken_payload_without_user_alerts_and_skips_receipt(self) -> None:
        payment = SuccessfulPayment(
            currency="XTR",
            total_amount=10,
            invoice_payload="broken",
            telegram_payment_charge_id="chg-orphan",
            provider_payment_charge_id="prov-orphan",
        )
        message = Message(
            message_id=1,
            date=1,
            chat=Chat(id=0, type="private"),
            successful_payment=payment,
        )
        self._update_id += 1
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, message=message))
        self.assertEqual(await self._tx_count("chg-orphan"), 0)
        self.consumer.on_voucher_issued.assert_not_awaited()
        self.assertTrue(
            any("Битый payload оплаты без пользователя" in item.text for item in self._named("SendMessage"))
        )

    async def test_payment_alert_respects_notify_flag(self) -> None:
        quiet = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.config.db_path,
            support_chat_id=-100,
            notify_on_payment=False,
        )
        dispatcher = Dispatcher()
        dispatcher.include_router(create_payments_router("bot_a", self.storage, quiet, self.consumer))
        self.dp = dispatcher
        await self._paid(7, "sku:vip:7:abcd", "chg-quiet", 5)
        self.consumer.on_voucher_issued.assert_awaited_once()
        self.assertFalse(self._named("SendMessage"))

    async def test_buy_sku_sends_stars_invoice_and_rejects_admin_grant(self) -> None:
        await self._buy(7, "buy_sku:vip")
        invoices = self._named("SendInvoice")
        self.assertEqual(len(invoices), 1)
        invoice = invoices[0]
        self.assertEqual(invoice.chat_id, 7)
        self.assertEqual(invoice.currency, "XTR")
        self.assertEqual(invoice.provider_token, "")
        self.assertFalse(invoice.is_flexible)
        self.assertEqual(invoice.prices[0].amount, 150)
        self.assertRegex(invoice.payload, r"^sku:vip:7:[0-9a-f]{8}$")
        self.assertFalse(self._named("AnswerCallbackQuery")[0].show_alert)

        self.session.requests.clear()
        await self._buy(7, "buy_sku:admin_grant")
        await self._buy(7, "buy_sku:missing")
        await self._buy(7, "buy_sku:")
        self.assertFalse(self._named("SendInvoice"))
        alerts = [item for item in self._named("AnswerCallbackQuery") if item.text == BUY_UNAVAILABLE]
        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(item.show_alert for item in alerts))

    async def _buy(self, user_id: int, data: str) -> None:
        user = User(id=user_id, is_bot=False, first_name="N")
        message = Message(message_id=1, date=1, chat=Chat(id=user_id, type="private"), from_user=user, text="buy")
        callback = CallbackQuery(
            id=f"buy-{self._update_id}",
            from_user=user,
            chat_instance="x",
            data=data,
            message=message,
        )
        self._update_id += 1
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, callback_query=callback))

    async def _pre_checkout(self, user_id: int, payload: str) -> None:
        query = PreCheckoutQuery(
            id=f"pq-{payload}-{user_id}-{self._update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="N"),
            currency="XTR",
            total_amount=1,
            invoice_payload=payload,
        )
        self._update_id += 1
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, pre_checkout_query=query))

    async def _paid(self, user_id: int, payload: str, charge_id: str, amount: int) -> None:
        payment = SuccessfulPayment(
            currency="XTR",
            total_amount=amount,
            invoice_payload=payload,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=f"prov-{charge_id}",
        )
        message = Message(
            message_id=1,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="N"),
            successful_payment=payment,
        )
        self._update_id += 1
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, message=message))

    def _answers(self):
        return self._named("AnswerPreCheckoutQuery")

    def _named(self, name: str) -> list[TelegramMethod]:
        return [item for item in self.session.requests if item.__class__.__name__ == name]

    async def _tx(self, payment_id: str) -> tuple[str, int, str, str]:
        def _op(conn):
            row = conn.execute(
                """
                SELECT sku_code, amount, provider, status FROM transactions
                WHERE bot_id = ? AND payment_id = ?
                """,
                ("bot_a", payment_id),
            ).fetchone()
            return (row["sku_code"], int(row["amount"]), row["provider"], row["status"])

        return await self.storage.engine.run(_op)

    async def _tx_count(self, payment_id: str) -> int:
        def _op(conn) -> int:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM transactions WHERE bot_id = ? AND payment_id = ?",
                ("bot_a", payment_id),
            ).fetchone()
            return int(row["n"])

        return await self.storage.engine.run(_op)


if __name__ == "__main__":
    unittest.main()
