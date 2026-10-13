"""Gate P1–P3: отмена инвойса, слоты кабинета и single-message /start."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
    User,
)

from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.factory import create_complete_chassis
from bot_chassis.localization import ChassisScreen
from bot_chassis.payments import CB_PAY_CANCEL, create_payments_router
from bot_chassis.payments.service import send_sku_invoice
from bot_chassis.ports.cabinet import CabinetSlot, build_cabinet_renderer


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


class _Slots:
    def __init__(self, slots: tuple[CabinetSlot, ...]) -> None:
        self.slots = slots

    async def get_cabinet_slots(self, bot_id: str, user_id: int) -> tuple[CabinetSlot, ...]:
        return self.slots


class TestCabinetSlots(unittest.IsolatedAsyncioTestCase):
    async def test_cabinet_slots_are_one_line_without_blank_gap(self) -> None:
        renderer = build_cabinet_renderer(
            _Slots(
                (
                    CabinetSlot("access", "Доступ", "VIP"),
                    CabinetSlot("vouchers", "Талоны", "1"),
                )
            ),
            "bot_a",
        )
        screen = await renderer(AsyncMock(), 7, AsyncMock())
        self.assertEqual(
            screen.text,
            "👤 <b>Аккаунт</b>\n\n• <b>Доступ:</b> VIP\n• <b>Талоны:</b> 1",
        )
        self.assertNotIn("\n\n• <b>Талоны", screen.text)

    async def test_cabinet_slot_html_is_escaped_once(self) -> None:
        renderer = build_cabinet_renderer(
            _Slots((CabinetSlot("x", 'A<B>&"C', "x<y>&z"),)),
            "bot_a",
        )
        screen = await renderer(AsyncMock(), 7, AsyncMock())
        self.assertIn("• <b>A&lt;B&gt;&amp;&quot;C:</b> x&lt;y&gt;&amp;z", screen.text)
        self.assertNotIn("&amp;lt;", screen.text)
        self.assertNotIn("&amp;amp;", screen.text)

    async def test_empty_cabinet_has_no_trailing_blank_line(self) -> None:
        renderer = build_cabinet_renderer(_Slots(()), "bot_a")
        screen = await renderer(AsyncMock(), 7, AsyncMock())
        self.assertEqual(screen.text, "👤 <b>Аккаунт</b>")
        self.assertFalse(screen.text.endswith("\n"))

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


_START_CASES = (
    "legacy_false",
    "no_callback",
    "plain_screen",
    "inline_screen",
    "language_toggle",
    "returned_message",
    "none_without_language",
    "none_with_language",
    "unsupported_result",
)


class _StartSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        if method.__class__.__name__ == "SendMessage":
            return Message(
                message_id=len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 7), type="private"),
                text=getattr(method, "text", "") or "",
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _kind(markup: object) -> str:
    if isinstance(markup, ReplyKeyboardMarkup):
        return "reply"
    if isinstance(markup, InlineKeyboardMarkup):
        return "inline"
    return "none"


class TestSingleMessageStart(unittest.IsolatedAsyncioTestCase):
    async def test_single_message_start_branch_matrix(self) -> None:
        for case_id in _START_CASES:
            with self.subTest(case_id=case_id):
                await self._run_case(case_id)

    async def _run_case(self, case_id: str) -> None:
        calls: list[int] = []
        inline = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Go", callback_data="go")]]
        )

        async def callback(context):
            calls.append(1)
            if case_id == "returned_message":
                return await context.message.answer("OWN")
            if case_id in {"none_without_language", "none_with_language"}:
                return None
            if case_id == "unsupported_result":
                return object()
            if case_id == "inline_screen":
                return ChassisScreen(text="BODY", markup=inline)
            return ChassisScreen(text="BODY")

        single = case_id != "legacy_false"
        language = case_id in {"language_toggle", "none_with_language"}
        tmp = tempfile.TemporaryDirectory()
        session = _StartSession()
        bot = Bot(token="123456:ABC", session=session)
        try:
            config = BotChassisConfig(
                bot_id="bot_a",
                db_path=os.path.join(tmp.name, "chassis.db"),
                enable_admin=False,
                enable_payments=False,
                enable_language_switch=language,
            )
            chassis = await create_complete_chassis(
                bot,
                config,
                render_start_callback=None if case_id == "no_callback" else callback,
                single_message_start=single,
            )
            await _feed_start(chassis, bot, 1)
            sends = [item for item in session.requests if item.__class__.__name__ == "SendMessage"]
            edits = [item for item in session.requests if item.__class__.__name__.startswith("Edit")]
            kinds = [_kind(getattr(item, "reply_markup", None)) for item in sends]
            self.assertNotIn("inline+reply", kinds)
            self.assertTrue(all(kind in {"reply", "inline", "none"} for kind in kinds))
            for item in sends:
                markup = getattr(item, "reply_markup", None)
                self.assertFalse(
                    isinstance(markup, ReplyKeyboardMarkup) and isinstance(markup, InlineKeyboardMarkup)
                )
            if case_id == "legacy_false":
                self.assertEqual(calls, [1])
                self.assertEqual([item.text for item in sends], ["Главное меню", "BODY"])
                self.assertEqual(kinds, ["reply", "none"])
                self.assertEqual(chassis.screens.get_card(7)[1], 2)
            elif case_id == "no_callback":
                self.assertEqual(calls, [])
                self.assertEqual([item.text for item in sends], ["Главное меню"])
                self.assertEqual(kinds, ["reply"])
                self.assertIsNone(chassis.screens.get_card(7))
            elif case_id == "plain_screen":
                self.assertEqual(calls, [1])
                self.assertEqual([item.text for item in sends], ["BODY"])
                self.assertEqual(kinds, ["reply"])
                self.assertIsNone(chassis.screens.get_card(7))
            elif case_id == "inline_screen":
                self.assertEqual(calls, [1])
                self.assertEqual([item.text for item in sends], ["Главное меню", "BODY"])
                self.assertEqual(kinds, ["reply", "inline"])
                card_id = chassis.screens.get_card(7)[1]
                self.assertEqual(card_id, 2)
                await _feed_start(chassis, bot, 2)
                self.assertEqual(calls, [1, 1])
                deleted = [
                    item.message_id
                    for item in session.requests
                    if item.__class__.__name__ == "DeleteMessage"
                ]
                self.assertIn(card_id, deleted)
            elif case_id == "language_toggle":
                self.assertEqual(calls, [1])
                self.assertEqual(kinds[0], "reply")
                self.assertEqual(sends[0].text, "Главное меню")
                self.assertEqual(kinds[1], "inline")
                self.assertEqual(sends[1].text, "BODY")
                self.assertEqual(chassis.screens.get_card(7)[1], 2)
            elif case_id == "returned_message":
                self.assertEqual(calls, [1])
                self.assertEqual([item.text for item in sends], ["OWN", "Главное меню"])
                self.assertEqual(kinds, ["none", "reply"])
                self.assertEqual(edits, [])
                self.assertEqual(chassis.screens.get_card(7)[1], 1)
            elif case_id == "none_without_language":
                self.assertEqual(calls, [1])
                self.assertEqual([item.text for item in sends], ["Главное меню"])
                self.assertEqual(kinds, ["reply"])
                self.assertIsNone(chassis.screens.get_card(7))
            elif case_id == "none_with_language":
                self.assertEqual(calls, [1])
                self.assertEqual(sends[0].text, "Главное меню")
                self.assertEqual(kinds[0], "reply")
                self.assertIn("Главное меню / Main menu", sends[1].text)
                self.assertEqual(kinds[1], "inline")
                self.assertEqual(chassis.screens.get_card(7)[1], 2)
            elif case_id == "unsupported_result":
                self.assertEqual(calls, [1])
                self.assertEqual([item.text for item in sends], ["Главное меню"])
                self.assertEqual(kinds, ["reply"])
                self.assertIsNone(chassis.screens.get_card(7))
            self.assertTrue(all(kind != "both" for kind in kinds))
        finally:
            await bot.session.close()
            tmp.cleanup()


async def _feed_start(chassis, bot: Bot, update_id: int) -> None:
    user = User(id=7, is_bot=False, first_name="Ann")
    await chassis.dp.feed_update(
        bot,
        Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=1,
                chat=Chat(id=7, type="private"),
                from_user=user,
                text="/start",
            ),
        ),
    )
