"""Gate P1: отмена инвойса Stars."""

from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, Message, Update, User

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.payments import CB_PAY_CANCEL, create_payments_router
from bot_chassis.payments.service import send_sku_invoice


class TestInvoiceCancelMarkup(unittest.IsolatedAsyncioTestCase):
    async def test_invoice_pay_button_is_first_and_cancel_is_second_row(self) -> None:
        bot = AsyncMock()
        sku = SkuItem(sku_code="vip", title="VIP", description="Месяц", stars_price=150)
        config = BotChassisConfig(bot_id="bot_a", skus=(sku,))
        self.assertTrue(await send_sku_invoice(bot, 7, config, "vip", 7))
        rows = bot.send_invoice.await_args.kwargs["reply_markup"].inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0][0].pay)
        self.assertEqual(rows[0][0].text, "Оплатить 150 ⭐")
        self.assertEqual(len(rows[1]), 1)
        self.assertEqual(rows[1][0].text, "Отмена")
        self.assertEqual(rows[1][0].callback_data, CB_PAY_CANCEL)
        self.assertFalse(getattr(rows[1][0], "pay", False))

    def test_invoice_cancel_callback_is_constant_under_64_bytes(self) -> None:
        long_sku = "x" * 120
        self.assertEqual(CB_PAY_CANCEL, "chassis:pay:cancel")
        self.assertLess(len(CB_PAY_CANCEL.encode("utf-8")), 64)
        self.assertNotIn(long_sku, CB_PAY_CANCEL)
        self.assertNotIn("sku", CB_PAY_CANCEL)


class _Storage:
    def __getattr__(self, name: str):
        raise AssertionError(f"storage.{name}")


class _Session(BaseSession):
    def __init__(self, delete_error: Exception | None = None, edit_error: Exception | None = None) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.delete_error = delete_error
        self.edit_error = edit_error

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        name = method.__class__.__name__
        if name == "DeleteMessage" and self.delete_error is not None:
            raise self.delete_error
        if name == "EditMessageReplyMarkup" and self.edit_error is not None:
            raise self.edit_error
        self.requests.append(method)
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestInvoiceCancelHandler(unittest.IsolatedAsyncioTestCase):
    async def test_invoice_cancel_does_not_touch_storage(self) -> None:
        session = _Session()
        await _press_cancel(session, _Storage())
        names = [item.__class__.__name__ for item in session.requests]
        self.assertEqual(names.count("AnswerCallbackQuery"), 1)
        self.assertEqual(session.requests[0].text, "Оплата отменена")
        self.assertNotIn("PreCheckoutQuery", names)
        self.assertFalse(any(name.startswith("Send") for name in names))

    async def test_invoice_cancel_answers_once_and_closes(self) -> None:
        success = _Session()
        await _press_cancel(success, _Storage())
        self.assertEqual(
            [item.__class__.__name__ for item in success.requests],
            ["AnswerCallbackQuery", "DeleteMessage"],
        )

        missing = _Session(
            delete_error=TelegramBadRequest(
                method=DeleteMessage(chat_id=7, message_id=4),
                message="not found",
            )
        )
        await _press_cancel(missing, _Storage())
        self._assert_markup_fallback(missing)

        forbidden = _Session(
            delete_error=TelegramForbiddenError(
                method=DeleteMessage(chat_id=7, message_id=4),
                message="blocked",
            )
        )
        await _press_cancel(forbidden, _Storage())
        self._assert_markup_fallback(forbidden)

        broken = _Session(
            delete_error=TelegramBadRequest(
                method=DeleteMessage(chat_id=7, message_id=4),
                message="not found",
            ),
            edit_error=RuntimeError("markup edit failed"),
        )
        await _press_cancel(broken, _Storage())
        self.assertEqual([item.__class__.__name__ for item in broken.requests], ["AnswerCallbackQuery"])

        ghost = _Session()
        await _press_cancel(
            ghost,
            _Storage(),
            message=InaccessibleMessage(chat=Chat(id=7, type="private"), message_id=4, date=0),
        )
        self.assertEqual([item.__class__.__name__ for item in ghost.requests], ["AnswerCallbackQuery"])
        self.assertEqual(ghost.requests[0].text, "Оплата отменена")

    def _assert_markup_fallback(self, session: _Session) -> None:
        names = [item.__class__.__name__ for item in session.requests]
        self.assertEqual(names.count("AnswerCallbackQuery"), 1)
        edits = [item for item in session.requests if item.__class__.__name__ == "EditMessageReplyMarkup"]
        self.assertEqual(len(edits), 1)
        self.assertIsNone(edits[0].reply_markup)
        self.assertNotIn("DeleteMessage", names)


async def _press_cancel(
    session: _Session,
    storage: object,
    message: Message | InaccessibleMessage | None = None,
) -> None:
    bot = Bot(token="123456:ABC", session=session)
    try:
        dp = Dispatcher()
        dp.include_router(create_payments_router("bot_a", storage, BotChassisConfig(bot_id="bot_a"), None))
        user = User(id=7, is_bot=False, first_name="Ann")
        if message is None:
            message = Message(
                message_id=4,
                date=int(time.time()),
                chat=Chat(id=7, type="private"),
                from_user=user,
                text="invoice",
            )
        await dp.feed_update(
            bot,
            Update(
                update_id=1,
                callback_query=CallbackQuery(
                    id="pay-cancel",
                    from_user=user,
                    chat_instance="x",
                    data=CB_PAY_CANCEL,
                    message=message,
                ),
            ),
        )
    finally:
        await bot.session.close()
