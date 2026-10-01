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
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
    User,
)

from bot_chassis.commands import setup_bot_commands
from bot_chassis.config import BotChassisConfig
from bot_chassis.contracts import (
    BTN_INFO_EN,
    BTN_INFO_RU,
    BTN_SUPPORT_RU,
    is_main_menu_button,
)
from bot_chassis.factory import create_complete_chassis
from bot_chassis.keyboards import (
    append_back_row,
    append_cancel_row,
    build_donation_keyboard,
    build_main_menu_keyboard,
    build_support_overview_keyboard,
    build_support_prompt_keyboard,
)
from bot_chassis.localization import ChassisScreen
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
        self.assertEqual(BTN_INFO_RU, "ℹ️ Инфо/FAQ")
        self.assertEqual(BTN_INFO_EN, "ℹ️ Info/FAQ")
        self.assertTrue(is_main_menu_button("ℹ️ Info"))
        self.assertTrue(is_main_menu_button("ℹ️ Info / FAQ ❓"))
        self.assertTrue(is_main_menu_button("ℹ️ Info/FAQ"))
        keyboard = build_main_menu_keyboard(locale="en", domain_rows=(("Chats",),))
        self.assertEqual(
            [[button.text for button in row] for row in keyboard.keyboard],
            [["Chats"], ["👤 Account", "ℹ️ Info/FAQ", "💬 Support"]],
        )

    def test_ru_labels_0_3_1_and_legacy_aliases(self) -> None:
        ru = build_main_menu_keyboard(locale="ru")
        self.assertEqual(len(ru.keyboard), 1)
        self.assertEqual(
            [button.text for button in ru.keyboard[0]],
            ["👤 Аккаунт", "ℹ️ Инфо/FAQ", "Поддержка"],
        )
        en = build_main_menu_keyboard(locale="en")
        self.assertEqual(
            [button.text for button in en.keyboard[0]],
            ["👤 Account", "ℹ️ Info/FAQ", "💬 Support"],
        )
        self.assertTrue(is_main_menu_button("👤 Личный кабинет"))
        self.assertTrue(is_main_menu_button("💬 Поддержка"))
        self.assertTrue(is_main_menu_button("ℹ️ Info/FAQ"))
        self.assertEqual(BTN_SUPPORT_RU, "Поддержка")

    async def test_visible_commands_are_menu_plus_explicit_body_commands(self) -> None:
        bot = AsyncMock()
        await setup_bot_commands(
            bot,
            custom_commands=[
                BotCommand(command="menu", description="Подмена"),
                BotCommand(command="start", description="Скрытая"),
                BotCommand(command="help", description="Скрытая"),
                BotCommand(command="support", description="Скрытая"),
                BotCommand(command="detect", description="Проверить"),
            ],
        )
        commands = bot.set_my_commands.await_args.args[0]
        self.assertEqual([(item.command, item.description) for item in commands], [
            ("menu", "📱 Восстановить кнопки меню"),
            ("detect", "Проверить"),
        ])

    async def test_info_click_sends_one_card_for_new_and_legacy_labels(self) -> None:
        calls: list[str] = []

        async def render_info(message: Message, user_id: int, bot: Bot) -> ChassisScreen:
            del user_id, bot
            calls.append(message.text or "")
            return ChassisScreen(text="INFO CARD")

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

        async def render_start(context):
            cards.append(context.locale)
            return await context.message.answer("START CARD")

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
        self.assertEqual(cards, ["en"])
        self.assertEqual(_send_texts(self.session), ["<b>Носитель</b>", "START CARD"])

    async def test_start_without_callback_sends_carrier_then_card(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=False,
        )
        chassis = await create_complete_chassis(self.bot, config)
        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=_private_message(8, "/start")))
        texts = _send_texts(self.session)
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts[0], "Главное меню")
        self.assertIn("Используйте кнопки", texts[1])
        carrier = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"][0]
        self.assertIsNotNone(carrier.reply_markup)
        card = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"][1]
        self.assertIsNone(card.reply_markup)

    async def test_leftover_body_start_is_rejected_during_assembly(self) -> None:
        domain = Router(name="domain")

        @domain.message(Command("start"))
        async def body_start(message: Message) -> None:
            await message.answer("BODY START")

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
        )
        with self.assertRaisesRegex(ValueError, "единый /start принадлежит bot_chassis"):
            await create_complete_chassis(
                self.bot,
                config,
                domain_router=domain,
            )

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

    async def test_navigation_canon_cancel_and_back(self) -> None:
        overview = build_support_overview_keyboard(show_review=True, show_donate=True)
        overview_cb = [
            button.callback_data
            for row in overview.inline_keyboard
            for button in row
        ]
        self.assertIn("core_nav:cancel", overview_cb)
        self.assertNotIn("core_sup:back", overview_cb)
        self.assertEqual(overview.inline_keyboard[-1][0].text, "Отмена")

        prompt = build_support_prompt_keyboard()
        self.assertEqual(len(prompt.inline_keyboard[-1]), 1)
        self.assertEqual(prompt.inline_keyboard[-1][0].text, "Назад")
        self.assertEqual(prompt.inline_keyboard[-1][0].callback_data, "core_sup:hub")

        mixed = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="A", callback_data="a"),
                InlineKeyboardButton(text="old", callback_data="core_nav:cancel"),
            ]]
        )
        once = append_cancel_row(mixed)
        twice = append_cancel_row(once)
        self.assertEqual(
            [[(b.text, b.callback_data) for b in row] for row in twice.inline_keyboard],
            [[("A", "a")], [("Отмена", "core_nav:cancel")]],
        )
        back = append_back_row(None, callback_data="core_sup:hub")
        back2 = append_back_row(back, callback_data="core_sup:hub")
        self.assertEqual(len(back2.inline_keyboard), 1)
        self.assertEqual(back2.inline_keyboard[0][0].text, "Назад")
        donate = build_donation_keyboard([("50 ⭐", "buy_sku:d50")])
        self.assertEqual(donate.inline_keyboard[-1][0].text, "Назад")
        self.assertEqual(donate.inline_keyboard[-1][0].callback_data, "core_sup:hub")
        review_prompt = build_support_prompt_keyboard()
        self.assertEqual(review_prompt.inline_keyboard[-1][0].callback_data, "core_sup:hub")

        starts: list[str] = []

        async def render_start(context):
            starts.append("ok")
            return ChassisScreen(text="START CARD")

        async def render_info(message, user_id, bot):
            return ChassisScreen(
                text="INFO ROOT",
                markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="More", callback_data="info:more")]]
                ),
            )

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            welcome_text="carrier",
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=True,
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            render_start_callback=render_start,
            render_info_callback=render_info,
        )

        await chassis.dp.feed_update(self.bot, Update(update_id=1, message=_private_message(7, "/start")))
        start_msgs = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertEqual([item.text for item in start_msgs], ["carrier", "START CARD"])
        self.assertIsInstance(start_msgs[0].reply_markup, ReplyKeyboardMarkup)
        self.assertNotIsInstance(start_msgs[1].reply_markup, ReplyKeyboardMarkup)
        self.assertEqual(starts, ["ok"])

        self.session.requests.clear()
        await chassis.dp.feed_update(
            self.bot,
            Update(update_id=6, message=_private_message(7, BTN_INFO_RU, 20)),
        )
        info_msg = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"][0]
        rows = info_msg.reply_markup.inline_keyboard
        self.assertEqual(rows[-1][0].text, "Отмена")
        self.assertEqual(rows[-1][0].callback_data, "core_nav:cancel")
        self.assertTrue(any((b.callback_data or "").startswith("core_lang:") for r in rows[:-1] for b in r))

        async def _callback(uid: int, data: str, mid: int, update_id: int) -> None:
            user = User(id=uid, is_bot=False, first_name="N")
            msg = Message(
                message_id=mid,
                date=1,
                chat=Chat(id=uid, type="private"),
                from_user=user,
                text="card",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="x", callback_data=data)]]
                ),
            ).as_(self.bot)
            await chassis.dp.feed_update(
                self.bot,
                Update(
                    update_id=update_id,
                    callback_query=CallbackQuery(
                        id=str(update_id),
                        from_user=user,
                        chat_instance="x",
                        data=data,
                        message=msg,
                    ).as_(self.bot),
                ),
            )

        self.session.requests.clear()
        starts.clear()
        await _callback(7, "core_nav:cancel", 10, 2)
        self.assertEqual(starts, ["ok"])
        cancel_sends = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertEqual([item.text for item in cancel_sends], ["START CARD"])
        self.assertTrue(all(not isinstance(item.reply_markup, ReplyKeyboardMarkup) for item in cancel_sends))

        self.session.requests.clear()
        starts.clear()
        await _callback(7, "core_sup:back", 11, 3)
        self.assertEqual(starts, ["ok"])
        self.assertEqual(
            [item.text for item in self.session.requests if item.__class__.__name__ == "SendMessage"],
            ["START CARD"],
        )

        self.session.requests.clear()
        starts.clear()
        await _callback(7, "core_nav:close", 12, 4)
        self.assertEqual(starts, [])
        self.assertEqual(
            [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"],
            [],
        )

        # Свежий user_id: иначе throttling глушит серию callback'ов одного юзера.
        self.session.requests.clear()
        await _callback(77, "core_sup:cancel", 13, 5)
        hub_texts = [
            item.text
            for item in self.session.requests
            if item.__class__.__name__ in {"SendMessage", "EditMessageText"}
            and item.text
        ]
        self.assertTrue(
            any("Поддержка" in text and "Выберите действие" in text for text in hub_texts),
            hub_texts,
        )

        # Без render_start и без языка — всё равно карточка, без Reply Keyboard.
        self.session.requests.clear()
        config2 = BotChassisConfig(
            bot_id="bot_b",
            db_path=os.path.join(self._tmp.name, "b.db"),
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=False,
        )
        chassis2 = await create_complete_chassis(self.bot, config2)
        user = User(id=9, is_bot=False, first_name="N")
        msg = Message(
            message_id=30,
            date=1,
            chat=Chat(id=9, type="private"),
            from_user=user,
            text="card",
        ).as_(self.bot)
        await chassis2.dp.feed_update(
            self.bot,
            Update(
                update_id=7,
                callback_query=CallbackQuery(
                    id="7",
                    from_user=user,
                    chat_instance="x",
                    data="core_nav:cancel",
                    message=msg,
                ).as_(self.bot),
            ),
        )
        fallback = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(len(fallback), 1)
        self.assertIn("Главное меню", fallback[0].text)
        self.assertNotIsInstance(fallback[0].reply_markup, ReplyKeyboardMarkup)

        # Callback вернул None → штатный fallback.
        self.session.requests.clear()

        async def render_none(context):
            return None

        config3 = BotChassisConfig(
            bot_id="bot_c",
            db_path=os.path.join(self._tmp.name, "c.db"),
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=False,
        )
        chassis3 = await create_complete_chassis(
            self.bot,
            config3,
            render_start_callback=render_none,
        )
        await chassis3.dp.feed_update(
            self.bot,
            Update(
                update_id=8,
                callback_query=CallbackQuery(
                    id="8",
                    from_user=user,
                    chat_instance="x",
                    data="core_nav:cancel",
                    message=msg,
                ).as_(self.bot),
            ),
        )
        none_fallback = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(len(none_fallback), 1)
        self.assertIn("Главное меню", none_fallback[0].text)

        # on_support_back вернул None после своей карточки — второго fallback нет.
        self.session.requests.clear()
        calls = {"n": 0}

        async def render_ok(context):
            calls["n"] += 1
            return ChassisScreen(text="ONE")

        config4 = BotChassisConfig(
            bot_id="bot_d",
            db_path=os.path.join(self._tmp.name, "d.db"),
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=False,
        )
        chassis4 = await create_complete_chassis(
            self.bot,
            config4,
            render_start_callback=render_ok,
        )
        await chassis4.dp.feed_update(
            self.bot,
            Update(
                update_id=9,
                callback_query=CallbackQuery(
                    id="9",
                    from_user=user,
                    chat_instance="x",
                    data="core_nav:cancel",
                    message=msg,
                ).as_(self.bot),
            ),
        )
        one = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(calls["n"], 1)
        self.assertEqual([item.text for item in one], ["ONE"])

        # Роутер без on_support_back — одна нейтральная fallback-карточка.
        self.session.requests.clear()
        dispatcher = Dispatcher()
        dispatcher.include_router(create_button_chassis_router())
        await dispatcher.feed_update(
            self.bot,
            Update(
                update_id=10,
                callback_query=CallbackQuery(
                    id="10",
                    from_user=user,
                    chat_instance="x",
                    data="core_nav:cancel",
                    message=msg,
                ).as_(self.bot),
            ),
        )
        bare = [item for item in self.session.requests if item.__class__.__name__ == "SendMessage"]
        self.assertEqual(len(bare), 1)
        self.assertIn("Главное меню", bare[0].text)
        self.assertNotIsInstance(bare[0].reply_markup, ReplyKeyboardMarkup)
