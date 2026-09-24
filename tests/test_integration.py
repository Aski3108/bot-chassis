"""Сквозной цикл рамы: старт, тень и платёж, кабинет, досье, возврат."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.contracts import BTN_CABINET_RU
from bot_chassis.factory import create_complete_chassis
from bot_chassis.payments.router import SHADOW_PAYMENT_ERROR


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name in {"SendMessage", "EditMessageText"}:
            return Message(
                message_id=50,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestChassisCycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "cycle.db")
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self._update_id = 1
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            enable_referrals=True,
            enable_payments=True,
            skus=(SkuItem("vip", "VIP", "Демо", 150),),
        )
        self.chassis = await create_complete_chassis(self.bot, self.config)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def test_start_shadow_payment_cabinet_dossier_and_refund(self) -> None:
        await self._text(7, "/start ref_100", username="ann")
        user = await self.chassis.storage.users.get_user("bot_a", 7)
        self.assertEqual(user.traffic_source, "ref_100")
        self.assertEqual(await self.chassis.storage.referrals.get_referrals_count("bot_a", 100), 1)
        menu = self._texts(7)
        self.assertTrue(any("Главное меню" in text for text in menu))

        await self._text(7, BTN_CABINET_RU, username="ann")
        cabinet = "\n".join(self._texts(7))
        self.assertIn("Личный кабинет", cabinet)
        self.assertIn("ID: 7 | @ann | Зарегистрирован:", cabinet)
        self.assertIn("Доступ: Базовый", cabinet)
        self.assertIn("Доступно талонов: 0", cabinet)
        self.assertIn("Приглашено друзей: 0", cabinet)
        self.assertIn("ref_7", cabinet)

        await self.chassis.storage.users.upsert_user("bot_a", 8, username="shade")
        ok, err = await self.chassis.storage.users.set_shadow_ban("bot_a", 8, True)
        self.assertTrue(ok)
        self.assertIsNone(err)
        before = len(self._texts(8))
        await self._text(8, BTN_CABINET_RU, username="shade")
        self.assertEqual(len(self._texts(8)), before)

        await self._pre_checkout(8, "sku:vip:8:abcd")
        answers = [item for item in self.session.requests if item.__class__.__name__ == "AnswerPreCheckoutQuery"]
        self.assertEqual(len(answers), 1)
        self.assertFalse(answers[0].ok)
        self.assertEqual(answers[0].error_message, SHADOW_PAYMENT_ERROR)
        self.assertNotIn("бан", answers[0].error_message.casefold())

        await self._paid(8, "sku:vip:8:abcd", "chg-shadow", 150)
        status, voucher = await self._payment("chg-shadow")
        self.assertEqual(status, "paid")
        self.assertEqual(voucher, "issued")

        await self._text(100, "/user 7")
        dossier = "\n".join(self._texts(100))
        self.assertIn("ID: 7", dossier)
        self.assertIn("Источник / Реф: ref_100", dossier)
        self.assertIn("Теневой бан: НЕТ", dossier)
        self.assertIn("Пригласил рефералов: 0", dossier)

        await self._text(100, "/user 8")
        shadow_card = self._texts(100)[-1]
        self.assertIn("Теневой бан: ДА", shadow_card)
        self.assertIn("Талоны: 1 шт. (Оплат всего: 1)", shadow_card)

        await self._text(100, "/refund 8 chg-shadow")
        self.assertTrue(any(item.__class__.__name__ == "RefundStarPayment" for item in self.session.requests))
        self.assertIn("Платёж возвращён: chg-shadow", self._texts(100)[-1])
        status, voucher = await self._payment("chg-shadow")
        self.assertEqual(status, "refunded")
        self.assertEqual(voucher, "cancelled")

    async def _text(self, user_id: int, text: str, username: str | None = None) -> None:
        message = Message(
            message_id=self._update_id,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="N", username=username),
            text=text,
        )
        self._update_id += 1
        await self.chassis.dp.feed_update(self.bot, Update(update_id=self._update_id, message=message))

    async def _pre_checkout(self, user_id: int, payload: str) -> None:
        query = PreCheckoutQuery(
            id=f"pq-{self._update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="N"),
            currency="XTR",
            total_amount=150,
            invoice_payload=payload,
        )
        self._update_id += 1
        await self.chassis.dp.feed_update(self.bot, Update(update_id=self._update_id, pre_checkout_query=query))

    async def _paid(self, user_id: int, payload: str, charge_id: str, amount: int) -> None:
        payment = SuccessfulPayment(
            currency="XTR",
            total_amount=amount,
            invoice_payload=payload,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=f"prov-{charge_id}",
        )
        message = Message(
            message_id=self._update_id,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="N"),
            successful_payment=payment,
        )
        self._update_id += 1
        await self.chassis.dp.feed_update(self.bot, Update(update_id=self._update_id, message=message))

    def _texts(self, chat_id: int) -> list[str]:
        return [
            item.text
            for item in self.session.requests
            if item.__class__.__name__ == "SendMessage" and item.chat_id == chat_id
        ]

    async def _payment(self, payment_id: str) -> tuple[str, str]:
        def _op(conn):
            row = conn.execute(
                """
                SELECT status, voucher_status FROM transactions
                WHERE bot_id = ? AND payment_id = ?
                """,
                ("bot_a", payment_id),
            ).fetchone()
            return row["status"], row["voucher_status"]

        return await self.chassis.storage.engine.run(_op)


if __name__ == "__main__":
    unittest.main()
