"""Узкий контракт Gate 1: клавиатура, алиасы, /menu, один Info и единый /start."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import Command
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from bot_chassis.commands import setup_bot_commands
from bot_chassis.config import BotChassisConfig
from bot_chassis.contracts import BTN_INFO_EN, BTN_INFO_RU, is_main_menu_button
from bot_chassis.factory import create_complete_chassis
from bot_chassis.keyboards import build_main_menu_keyboard
from bot_chassis.middleware.error_monitor import ErrorAlertMiddleware
from bot_chassis.router import create_button_chassis_router


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
                message_id=len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _private_message(user_id: int, text: str, message_id: int = 1) -> Message:
    return Message(
        message_id=message_id,
        date=1,
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="N"),
        text=text,
    )


def _send_texts(session: _Session) -> list[str]:
    return [item.text for item in session.requests if item.__class__.__name__ == "SendMessage"]


class TestGate1MenuContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    def test_service_buttons_share_one_row_and_old_info_label_stays_alias(self) -> None:
        self.assertEqual(BTN_INFO_RU, "ℹ️ Info/FAQ")
        self.assertEqual(BTN_INFO_EN, "ℹ️ Info/FAQ")
        self.assertTrue(is_main_menu_button("ℹ️ Info"))
        self.assertTrue(is_main_menu_button("ℹ️ Info / FAQ ❓"))
        keyboard = build_main_menu_keyboard(locale="en", domain_rows=(("Chats",),))
        self.assertEqual(
            [[button.text for button in row] for row in keyboard.keyboard],
            [["Chats"], ["👤 Account", "ℹ️ Info/FAQ", "💬 Support"]],
        )

    async def test_visible_commands_are_menu_plus_explicit_body_commands(self) -> None:
        bot = AsyncMock()
        await setup_bot_commands(bot, custom_commands=None)
        commands = bot.set_my_commands.await_args.args[0]
        self.assertEqual([(item.command, item.description) for item in commands], [
            ("menu", "📱 Восстановить кнопки меню"),
        ])

    async def test_info_click_sends_one_card_for_new_and_legacy_labels(self) -> None:
        calls: list[str] = []

        async def render_info(message: Message, user_id: int, bot: Bot) -> Message:
            calls.append(message.text or "")
            sent = await message.answer("INFO CARD")
            return sent

        dispatcher = Dispatcher()
        dispatcher.include_router(
            create_button_chassis_router(render_info_callback=render_info)
        )
        await dispatcher.feed_update(self.bot, Update(update_id=1, message=_private_message(7, "ℹ️ Info/FAQ")))
        await dispatcher.feed_update(self.bot, Update(update_id=2, message=_private_message(7, "ℹ️ Info", 2)))
        self.assertEqual(calls, ["ℹ️ Info/FAQ", "ℹ️ Info"])
        self.assertEqual(_send_texts(self.session), ["INFO CARD", "INFO CARD"])

    async def test_start_callback_gets_one_carrier_and_one_card(self) -> None:
        cards: list[str] = []

        async def render_start(context) -> None:
            cards.append(context.locale)
            await context.message.answer("START CARD")

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            welcome_text="<b>Носитель</b>",
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=False,
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            render_start_callback=render_start,
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=_private_message(7, "/start")))
        self.assertEqual(cards, ["ru"])
        self.assertEqual(_send_texts(self.session), ["<b>Носитель</b>", "START CARD"])

    async def test_start_without_callback_keeps_single_legacy_menu(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
        )
        chassis = await create_complete_chassis(self.bot, config)
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=_private_message(8, "/start")))
        texts = _send_texts(self.session)
        self.assertEqual(len(texts), 1)
        self.assertIn("Главное меню", texts[0])
        self.assertIn("Используйте кнопки", texts[0])

    async def test_leftover_body_start_does_not_add_chassis_reply(self) -> None:
        domain = Router(name="domain")
        body_hits = {"n": 0}

        @domain.message(Command("start"))
        async def body_start(message: Message) -> None:
            body_hits["n"] += 1
            await message.answer("BODY START")

        callback_hits = {"n": 0}

        async def render_start(context) -> None:
            callback_hits["n"] += 1
            await context.message.answer("START CARD")

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            domain_router=domain,
            render_start_callback=render_start,
        )
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=_private_message(9, "/start")))
        self.assertEqual(body_hits["n"], 1)
        self.assertEqual(callback_hits["n"], 0)
        self.assertEqual(_send_texts(self.session), ["BODY START"])

    async def test_unhandled_error_text_has_two_plain_lines(self) -> None:
        message = _private_message(3, "hi")
        update = Update(update_id=1, message=message)
        middleware = ErrorAlertMiddleware(
            BotChassisConfig(bot_id="bot_a", db_path=self.db_path, support_chat_id=-100)
        )

        async def boom(event, data):
            raise RuntimeError("bad <script>")

        bot = AsyncMock()
        with patch.object(Message, "answer", new_callable=AsyncMock) as answer:
            self.assertIsNone(await middleware(boom, update, {"bot": bot}))
        answer.assert_awaited_once_with(
            "Произошла непредвиденная ошибка.\nМы уже занимаемся этим вопросом."
        )
        alert = bot.send_message.await_args.args[1]
        self.assertIn("&lt;script&gt;", alert)
        self.assertNotIn("⚠️", answer.await_args.args[0])
