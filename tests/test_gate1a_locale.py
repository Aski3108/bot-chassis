"""Gate 1A: один toggle RU/EN, первая локаль и вечный ручной выбор."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

from bot_chassis.config import BotChassisConfig
from bot_chassis.factory import create_complete_chassis
from bot_chassis.localization import (
    ChassisScreen,
    InitialLocalePolicy,
    MarkupContext,
    decorate_info_markup,
    language_toggle_label,
    resolve_initial_locale,
)
from bot_chassis.middleware.user_activity import UserActivityMiddleware
from bot_chassis.router import create_button_chassis_router
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import StorageEngine


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name == "SendMessage":
            markup = getattr(method, "reply_markup", None)
            if markup is not None and markup.__class__.__name__ != "InlineKeyboardMarkup":
                markup = None
            return Message(
                message_id=len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
                reply_markup=markup,
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _user(user_id: int, language_code: str | None) -> User:
    return User(id=user_id, is_bot=False, first_name="N", language_code=language_code)


def _send_messages(session: _Session):
    return [item for item in session.requests if item.__class__.__name__ == "SendMessage"]


class TestInitialLocale(unittest.TestCase):
    def test_ru_group_regional_codes_and_unknown_fallback(self) -> None:
        ru_codes = ["ru", "be", "uk", "kk", "ky", "uz", "tg", "tk", "hy", "az", "ka", "pl"]
        for code in ru_codes:
            self.assertEqual(resolve_initial_locale(code), "ru", code)
            self.assertEqual(resolve_initial_locale(f"{code}-{code.upper()}"), "ru", code)
            self.assertEqual(resolve_initial_locale(f"{code}_{code.upper()}"), "ru", code)
        for raw in (None, "", "   ", "en", "en-CA", "fr", "de", "zh-Hans", "und"):
            self.assertEqual(resolve_initial_locale(raw), "en", repr(raw))

    def test_policy_can_extend_the_ru_group(self) -> None:
        policy = InitialLocalePolicy(ru_language_codes=frozenset({"de"}))
        self.assertEqual(resolve_initial_locale("de-DE", policy), "ru")
        self.assertEqual(resolve_initial_locale("pl", policy), "en")

    def test_toggle_labels_swap_order(self) -> None:
        self.assertEqual(language_toggle_label("ru"), "🌐 English / Русский")
        self.assertEqual(language_toggle_label("en"), "🌐 Русский / English")

    def test_decorate_adds_one_toggle_and_does_not_touch_question_rows(self) -> None:
        question = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Ответ", callback_data="q:1")]]
        )
        decorated = decorate_info_markup(question, MarkupContext(locale="ru", user_id=1))
        self.assertEqual(decorated.inline_keyboard[0][0].text, "Ответ")
        self.assertEqual(decorated.inline_keyboard[1][0].callback_data, "core_lang:toggle")
        again = decorate_info_markup(decorated, MarkupContext(locale="en"))
        toggles = [
            button
            for row in again.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("core_lang:")
        ]
        self.assertEqual(len(toggles), 1)
        self.assertEqual(toggles[0].text, "🌐 Русский / English")


class TestLocalePersistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.config = BotChassisConfig(bot_id="bot_a", db_path=self.db_path, enable_admin=False, enable_payments=False)
        self.storage = await create_storage(self.config)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_first_contact_then_manual_choice_is_never_overwritten(self) -> None:
        middleware = UserActivityMiddleware("bot_a", self.storage, self.config, locale_cache={})

        async def visit(language: str | None, update_id: int) -> None:
            user = _user(4, language)
            await middleware(
                AsyncMock(return_value="ok"),
                Update(update_id=update_id, message=Message(
                    message_id=update_id,
                    date=1,
                    chat=Chat(id=4, type="private"),
                    from_user=user,
                    text="hi",
                )),
                {"event_from_user": user},
            )

        await visit("pl-PL", 1)
        stored = await self.storage.users.get_user("bot_a", 4)
        self.assertEqual(stored.language_code, "ru")
        self.assertEqual(stored.locale_source, "auto")
        self.assertEqual(stored.telegram_language_code, "pl-PL")
        self.assertEqual(middleware._locale_cache[4], "ru")

        self.assertTrue(await self.storage.users.set_manual_locale("bot_a", 4, "en"))
        await visit("uk-UA", 2)
        stored = await self.storage.users.get_user("bot_a", 4)
        self.assertEqual(stored.language_code, "en")
        self.assertEqual(stored.locale_source, "manual")
        self.assertEqual(stored.telegram_language_code, "uk-UA")

    async def test_missing_language_code_starts_in_english(self) -> None:
        middleware = UserActivityMiddleware("bot_a", self.storage, self.config)
        user = _user(5, None)
        await middleware(
            AsyncMock(return_value="ok"),
            Update(update_id=1, message=Message(
                message_id=1, date=1, chat=Chat(id=5, type="private"), from_user=user, text="hi",
            )),
            {"event_from_user": user},
        )
        stored = await self.storage.users.get_user("bot_a", 5)
        self.assertEqual(stored.language_code, "en")
        self.assertEqual(stored.locale_source, "auto")

    async def test_existing_row_stays_legacy_across_repeated_migration(self) -> None:
        path = os.path.join(self._tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE users (
                bot_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                language_code TEXT NOT NULL DEFAULT 'ru',
                is_banned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (bot_id, user_id)
            )
            """
        )
        conn.execute("INSERT INTO users (bot_id, user_id, language_code) VALUES ('bot_a', 8, 'ru')")
        conn.commit()
        conn.close()
        engine = StorageEngine(path)
        await engine.initialize()
        await engine.initialize()

        def _read(connection):
            columns = [row[1] for row in connection.execute("PRAGMA table_info(users)")]
            user = connection.execute(
                "SELECT language_code, locale_source FROM users WHERE user_id = 8"
            ).fetchone()
            return columns, user["language_code"], user["locale_source"]

        columns, language, source = await engine.run(_read)
        self.assertEqual(columns.count("locale_source"), 1)
        self.assertEqual(columns.count("telegram_language_code"), 1)
        self.assertEqual(language, "ru")
        self.assertEqual(source, "legacy")


class TestLanguageToggleFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def test_toggle_edits_card_updates_keyboard_once_and_keeps_domain_step(self) -> None:
        domain = {"step": 3, "answers": ["a", "b"]}
        seen: list[tuple] = []

        async def on_locale_changed(context) -> None:
            seen.append((context.locale, domain["step"], list(domain["answers"])))

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=True,
        )
        chassis = await create_complete_chassis(
            self.bot,
            config,
            on_locale_changed=on_locale_changed,
        )
        await chassis.storage.users.record_telegram_visit("bot_a", 7, None, "N", None, "ru", "ru")
        chassis.locale_cache[7] = "ru"
        user = _user(7, "ru")
        chat = Chat(id=7, type="private")
        card = Message(
            message_id=10,
            date=1,
            chat=chat,
            from_user=user,
            text="Старт",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🌐 English / Русский", callback_data="core_lang:toggle")]]
            ),
        )

        async def click(update_id: int) -> None:
            await chassis.dp.feed_update(
                self.bot,
                Update(
                    update_id=update_id,
                    callback_query=CallbackQuery(
                        id=f"c{update_id}",
                        from_user=user,
                        chat_instance="x",
                        data="core_lang:toggle",
                        message=card,
                    ),
                ),
            )

        await click(1)
        await click(2)
        self.assertEqual(seen, [("en", 3, ["a", "b"]), ("ru", 3, ["a", "b"])])
        self.assertEqual(domain, {"step": 3, "answers": ["a", "b"]})
        stored = await chassis.storage.users.get_user("bot_a", 7)
        self.assertEqual(stored.language_code, "ru")
        self.assertEqual(stored.locale_source, "manual")
        edits = [item for item in self.session.requests if item.__class__.__name__ == "EditMessageReplyMarkup"]
        sends = _send_messages(self.session)
        self.assertEqual(len(edits), 2)
        self.assertEqual(len(sends), 2)
        self.assertNotIn("📱 Главное меню", sends[0].text)
        self.assertEqual(edits[0].reply_markup.inline_keyboard[0][0].text, "🌐 Русский / English")
        self.assertEqual(edits[1].reply_markup.inline_keyboard[0][0].text, "🌐 English / Русский")

    async def test_same_service_labels_do_not_send_another_menu(self) -> None:
        from bot_chassis.localization import create_localization_router

        storage = await create_storage(BotChassisConfig(bot_id="bot_a", db_path=self.db_path))
        await storage.users.upsert_user("bot_a", 9, language_code="ru")
        dispatcher = Dispatcher()
        dispatcher.include_router(
            create_localization_router(
                "bot_a",
                storage,
                enabled=True,
                locale_cache={9: "ru"},
                enable_cabinet=False,
                enable_support=False,
            )
        )
        user = _user(9, "ru")
        message = Message(
            message_id=1,
            date=1,
            chat=Chat(id=9, type="private"),
            from_user=user,
            text="x",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🌐 English / Русский", callback_data="core_lang:toggle")]]
            ),
        )
        await dispatcher.feed_update(
            self.bot,
            Update(
                update_id=1,
                callback_query=CallbackQuery(
                    id="c1",
                    from_user=user,
                    chat_instance="x",
                    data="core_lang:toggle",
                    message=message,
                ),
            ),
        )
        self.assertEqual(_send_messages(self.session), [])
        edits = [item for item in self.session.requests if item.__class__.__name__ == "EditMessageReplyMarkup"]
        self.assertEqual(len(edits), 1)

    async def test_start_card_and_info_card_carry_one_toggle(self) -> None:
        async def render_start(context):
            return ChassisScreen(text="START", markup=None)

        async def render_info(message, user_id, bot):
            return ChassisScreen(
                text="INFO",
                markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="Подробнее", callback_data="info:more")]]
                ),
            )

        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
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
        user = _user(11, "ru")
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=1,
                    chat=Chat(id=11, type="private"),
                    from_user=user,
                    text="/start",
                ),
            ),
        )
        start_sends = _send_messages(self.session)
        self.assertEqual([item.text for item in start_sends], ["Главное меню", "START"])
        start_toggle = [
            button
            for row in start_sends[1].reply_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("core_lang:")
        ]
        self.assertEqual(len(start_toggle), 1)
        self.session.requests.clear()
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=2,
                message=Message(
                    message_id=2,
                    date=1,
                    chat=Chat(id=11, type="private"),
                    from_user=user,
                    text="ℹ️ Info/FAQ",
                ),
            ),
        )
        info_sends = _send_messages(self.session)
        self.assertEqual([item.text for item in info_sends], ["INFO"])
        labels = [button.text for row in info_sends[0].reply_markup.inline_keyboard for button in row]
        self.assertEqual(labels, ["Подробнее", "🌐 English / Русский"])

    async def test_old_info_message_is_not_mutated(self) -> None:
        sent = Message(
            message_id=50,
            date=1,
            chat=Chat(id=12, type="private"),
            text="Уже отправлено",
        )

        async def render_info(message, user_id, bot):
            return sent

        dispatcher = Dispatcher()
        dispatcher.include_router(
            create_button_chassis_router(
                render_info_callback=render_info,
                language_switch_enabled=True,
            )
        )
        await dispatcher.feed_update(
            self.bot,
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=1,
                    chat=Chat(id=12, type="private"),
                    from_user=_user(12, "ru"),
                    text="ℹ️ Info/FAQ",
                ),
            ),
        )
        self.assertEqual(_send_messages(self.session), [])

    async def test_without_locale_callback_chassis_still_switches(self) -> None:
        config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            enable_admin=False,
            enable_payments=False,
            enable_language_switch=True,
        )
        chassis = await create_complete_chassis(self.bot, config)
        await chassis.storage.users.upsert_user("bot_a", 15, language_code="ru")
        user = _user(15, "en")
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=1,
                callback_query=CallbackQuery(
                    id="c1",
                    from_user=user,
                    chat_instance="x",
                    data="core_lang:en",
                    message=Message(
                        message_id=1,
                        date=1,
                        chat=Chat(id=15, type="private"),
                        from_user=user,
                        text="x",
                    ),
                ),
            ),
        )
        stored = await chassis.storage.users.get_user("bot_a", 15)
        self.assertEqual(stored.language_code, "en")
        self.assertEqual(stored.locale_source, "manual")
        self.assertEqual(chassis.locale_cache[15], "en")
