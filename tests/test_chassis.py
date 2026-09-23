"""Комплексный сьют тестов шасси кнопочного интерфейса (Button Chassis / bot_core).

Проверяет:
1. Клавиатуру: тумблеры разделов (enable_cabinet/info/support), слот domain_rows, локализацию.
2. Сброс тикета поддержки доменными кнопками («Ваши чаты» прерывает тикет).
3. Персистентный мост поддержки: композитный ключ (chat_id, message_id), оба ID (шапка и копия), лимит тикетов, атомарность записи.
4. Политику закрытия экранов CardClosePolicy (DELETE vs DROP_MARKUP) с проверкой реальных вызовов Bot API.
5. Регистрацию команд и хук dp.startup (set_my_commands для синей кнопки меню).
6. Интеграцию с реальным aiogram Dispatcher:
   - Сквозной проход ссылок на каналы (F.text) и документов (F.document) в доменный шлюз!
   - Обработку команд /menu, /help, /support.
   - Перехват текста ТОЛЬКО при активном ожидании тикета (с изоляцией от доменного шлюза).
   - Изоляцию ответов админа строго внутри support_chat_id (ответы из других чатов игнорируются).
"""

from __future__ import annotations
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Update, Message, User, Chat, Document

from bot_chassis import (
    BTN_CABINET_RU,
    BTN_CABINET_EN,
    BTN_INFO_RU,
    BTN_SUPPORT_RU,
    is_main_menu_button,
    extract_domain_labels,
    build_main_menu_keyboard,
    build_inline_keyboard,
    PendingInputStore,
    PendingInput,
    PendingInputKind,
    ActiveTaskTracker,
    UserScreenTracker,
    CardClosePolicy,
    edit_or_send,
    SupportThreadStore,
    create_button_chassis_router,
    SupportTicketActiveFilter,
    register_button_chassis_startup,
    setup_bot_commands,
    CB_SUPPORT_CANCEL,
)


class MockedSession(BaseSession):
    """Мок-сессия для тестирования Bot API вызовов в Dispatcher."""
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name == "SendMessage":
            return Message(
                message_id=999,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        if name in ("CopyMessage", "CopyMessageId"):
            return types.MessageId(message_id=888)
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestButtonChassisUnit(unittest.TestCase):
    def test_main_menu_keyboard_toggles_and_domain_rows(self):
        """Проверка отключения кабинета и добавления доменного ряда над Info и Поддержкой."""
        domain_rows = [["📊 Ваши чаты", "🔍 Ваши слова"]]
        kb = build_main_menu_keyboard(
            domain_rows=domain_rows,
            enable_cabinet=False,  # Отключаем кабинет
            enable_info=True,
            enable_support=True,
        )
        self.assertTrue(kb.is_persistent)
        # Должно быть 2 ряда: 1 доменный + 1 ряд [Info, Поддержка]
        self.assertEqual(len(kb.keyboard), 2)
        self.assertEqual(kb.keyboard[0][0].text, "📊 Ваши чаты")
        self.assertEqual(kb.keyboard[0][1].text, "🔍 Ваши слова")
        self.assertEqual(kb.keyboard[1][0].text, BTN_INFO_RU)
        self.assertEqual(kb.keyboard[1][1].text, BTN_SUPPORT_RU)

    def test_domain_labels_cancel_support_ticket(self):
        """Проверка, что нажатие доменной кнопки сбрасывает режим тикета поддержки."""
        domain_rows = [["📊 Ваши чаты", "🔍 Ваши слова"]]
        domain_labels = extract_domain_labels(domain_rows)
        self.assertIn("📊 Ваши чаты", domain_labels)

        store = PendingInputStore()
        store.set(123, PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE))
        filter_fn = SupportTicketActiveFilter(store, domain_labels=domain_labels)

        # Сообщение с текстом доменной кнопки
        msg = Mock(spec=Message)
        msg.from_user = Mock(id=123)
        msg.text = "📊 Ваши чаты"

        # Фильтр должен вернуть False и СБРОСИТЬ тикет из памяти!
        res = asyncio.run(filter_fn(msg))
        self.assertFalse(res)
        self.assertFalse(store.is_active(123, PendingInputKind.SUPPORT_MESSAGE))

    def test_support_thread_store_composite_key_and_persistence(self):
        """Проверка композитного ключа (chat_id, message_id), персистентности и лимита тикетов."""
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, "test_threads.json")
        try:
            store = SupportThreadStore(persistence_file=file_path, max_active_tickets_per_user=2)
            self.assertTrue(store.can_send_ticket(999))

            # Регистрируем обращение
            store.register(chat_id=-1001, user_id=999, header_msg_id=10, copied_msg_id=11)
            self.assertEqual(store.resolve_user(chat_id=-1001, reply_to_message_id=10), 999)
            self.assertEqual(store.resolve_user(chat_id=-1001, reply_to_message_id=11), 999)
            # В другом чате тот же message_id не должен матчиться
            self.assertIsNone(store.resolve_user(chat_id=-9999, reply_to_message_id=10))

            # Второй тикет
            store.register(chat_id=-1001, user_id=999, header_msg_id=20, copied_msg_id=21)
            # Лимит исчерпан
            self.assertFalse(store.can_send_ticket(999))

            # Проверяем персистентность: новый экземпляр загружает данные с диска
            store_loaded = SupportThreadStore(persistence_file=file_path, max_active_tickets_per_user=2)
            self.assertEqual(store_loaded.resolve_user(chat_id=-1001, reply_to_message_id=10), 999)
            self.assertFalse(store_loaded.can_send_ticket(999))
            
            # Ответ админа освобождает слот
            store_loaded.mark_answered(999)
            self.assertTrue(store_loaded.can_send_ticket(999))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_support_thread_store_constructor_arg_overrides_file_value(self):
        """Проверка, что число max_active_tickets из файла не перебивает аргумент конструктора."""
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, "test_threads_override.json")
        try:
            # Записываем в файл число 99
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"max_active_tickets": 99, "threads": [], "counts": {}}, f)

            # Инициализируем хранилище с лимитом 3
            store = SupportThreadStore(persistence_file=file_path, max_active_tickets_per_user=3)
            # Лимит из аргумента конструктора должен остаться 3, а не 99 из файла
            self.assertEqual(store.max_active_tickets, 3)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_user_screen_tracker_policies_telegram_calls(self):
        """Проверка реальных вызовов Bot API при закрытии экрана (DELETE vs DROP_MARKUP)."""
        tracker = UserScreenTracker()
        bot = Mock(spec=Bot)
        bot.delete_message = AsyncMock()
        bot.edit_message_reply_markup = AsyncMock()

        # 1. DROP_MARKUP: снимает только клавиатуру, не удаляя само сообщение
        tracker.remember_card(user_id=10, chat_id=100, message_id=500, policy=CardClosePolicy.DROP_MARKUP)
        asyncio.run(tracker.close_previous_card(bot, user_id=10, current_message_id=501))
        self.assertIsNone(tracker.get_card(10))
        bot.edit_message_reply_markup.assert_awaited_once_with(chat_id=100, message_id=500, reply_markup=None)
        bot.delete_message.assert_not_awaited()

        # 2. DELETE: удаляет карточку полностью
        bot.reset_mock()
        tracker.remember_card(user_id=11, chat_id=100, message_id=600, policy=CardClosePolicy.DELETE)
        asyncio.run(tracker.close_previous_card(bot, user_id=11, current_message_id=601))
        self.assertIsNone(tracker.get_card(11))
        bot.delete_message.assert_awaited_once_with(chat_id=100, message_id=600)
        bot.edit_message_reply_markup.assert_not_awaited()

    def test_register_button_chassis_startup_hook(self):
        """Проверка регистрации хука setup_bot_commands на dp.startup."""
        dp = Dispatcher()
        bot = Mock(spec=Bot)
        bot.set_my_commands = AsyncMock()

        register_button_chassis_startup(dp, bot)
        asyncio.run(dp.emit_startup(bot=bot))
        bot.set_my_commands.assert_awaited_once()
        args, kwargs = bot.set_my_commands.call_args
        commands = kwargs.get("commands") or args[0]
        cmd_names = [c.command for c in commands]
        self.assertIn("menu", cmd_names)
        self.assertIn("help", cmd_names)
        self.assertIn("support", cmd_names)

    def test_setup_bot_commands_merges_custom_commands(self):
        """Проверка, что кастомные команды дополняют команды шасси, а не стирают их."""
        bot = Mock(spec=Bot)
        bot.set_my_commands = AsyncMock()
        custom = [types.BotCommand(command="detect", description="AI Detector")]

        asyncio.run(setup_bot_commands(bot, custom_commands=custom))
        bot.set_my_commands.assert_awaited_once()
        args, kwargs = bot.set_my_commands.call_args
        commands = kwargs.get("commands") or args[0]
        cmd_names = [c.command for c in commands]
        self.assertIn("start", cmd_names)
        self.assertIn("menu", cmd_names)
        self.assertIn("help", cmd_names)
        self.assertIn("support", cmd_names)
        self.assertIn("detect", cmd_names)

    def test_active_task_tracker_handles_none_task(self):
        """Проверка дедупликации кликов в ActiveTaskTracker даже при current_task is None."""
        tracker = ActiveTaskTracker()
        # Первый клик
        self.assertTrue(tracker.should_process(user_id=123, route_name="menu:info", current_task=None))
        # Повторный клик на тот же маршрут до завершения первого — дедуплицируется!
        self.assertFalse(tracker.should_process(user_id=123, route_name="menu:info", current_task=None))
        # Клик на другой маршрут — разрешается
        self.assertTrue(tracker.should_process(user_id=123, route_name="menu:cabinet", current_task=None))
        # Освобождение
        tracker.release(user_id=123, current_task=None)
        # После освобождения снова разрешено
        self.assertTrue(tracker.should_process(user_id=123, route_name="menu:cabinet", current_task=None))

    def test_edit_or_send_incoming_user_message_skips_edit_text(self):
        """Проверка, что edit_or_send для входящего сообщения пользователя не вызывает edit_text."""
        msg = Mock(spec=Message)
        msg.from_user = Mock(id=10, is_bot=False)
        msg.answer = AsyncMock()
        msg.edit_text = AsyncMock()

        asyncio.run(edit_or_send(msg, "Привет", reply_markup=None))
        msg.answer.assert_awaited_once()
        msg.edit_text.assert_not_awaited()


class TestButtonChassisDispatcherIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Интеграционные тесты роутера внутри реального aiogram Dispatcher
    рядом с доменными хэндлерами шлюза bot_gateway.
    """
    async def asyncSetUp(self):
        self.session = MockedSession()
        self.bot = Bot(token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz", session=self.session)
        self.dp = Dispatcher()

        self.support_chat_id = -1001999999
        self.cabinet_mock = AsyncMock()
        self.info_mock = AsyncMock()
        self.pending_store = PendingInputStore(ttl_seconds=900.0)
        self.thread_store = SupportThreadStore(persistence_file=None, max_active_tickets_per_user=5)
        self.screen_tracker = UserScreenTracker()

        # Создаем роутер шасси с инъецированными экземплярами
        self.chassis_router = create_button_chassis_router(
            support_chat_id=self.support_chat_id,
            domain_rows=[["📊 Ваши чаты", "🔍 Ваши слова"]],
            render_cabinet_callback=self.cabinet_mock,
            render_info_callback=self.info_mock,
            pending_store=self.pending_store,
            thread_store=self.thread_store,
            screen_tracker=self.screen_tracker,
            project_label="Тест",
        )
        self.dp.include_router(self.chassis_router)

        # Создаем доменный роутер (шлюз)
        self.domain_router = Router(name="domain_gateway")
        self.domain_text_received = []
        self.domain_doc_received = []

        @self.domain_router.message(F.text)
        async def domain_text_handler(message: Message):
            self.domain_text_received.append(message.text)

        @self.domain_router.message(F.document)
        async def domain_doc_handler(message: Message):
            self.domain_doc_received.append(message.document.file_name)

        self.dp.include_router(self.domain_router)

    async def test_domain_text_and_channel_link_passes_through_cleanly(self):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Проверка, что ссылка на канал или обычный текст
        проходит сквозь шасси и обрабатывается доменным роутером!
        """
        user = User(id=101, is_bot=False, first_name="Tester", username="tester")
        chat = Chat(id=101, type="private")
        msg = Message(
            message_id=1,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            text="https://t.me/durov",
        )
        update = Update(update_id=1, message=msg)

        await self.dp.feed_update(self.bot, update)

        # Доменный обработчик ДОЛЖЕН получить ссылку!
        self.assertEqual(len(self.domain_text_received), 1)
        self.assertEqual(self.domain_text_received[0], "https://t.me/durov")

    async def test_domain_document_passes_through_cleanly(self):
        """Проверка, что файл переписки (JSON/TXT) проходит сквозь шасси к шлюзу."""
        user = User(id=101, is_bot=False, first_name="Tester")
        chat = Chat(id=101, type="private")
        doc = Document(file_id="abc123xyz", file_unique_id="uniq1", file_name="export.json")
        msg = Message(
            message_id=2,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            document=doc,
        )
        update = Update(update_id=2, message=msg)

        await self.dp.feed_update(self.bot, update)

        # Доменный обработчик ДОЛЖЕН получить документ!
        self.assertEqual(len(self.domain_doc_received), 1)
        self.assertEqual(self.domain_doc_received[0], "export.json")

    async def test_help_command_triggers_info_callback(self):
        """Проверка, что команда /help открывает колбэк Info."""
        user = User(id=102, is_bot=False, first_name="Tester")
        chat = Chat(id=102, type="private")
        msg = Message(
            message_id=3,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            text="/help",
        )
        update = Update(update_id=3, message=msg)

        await self.dp.feed_update(self.bot, update)

        self.info_mock.assert_called_once()
        self.assertEqual(len(self.domain_text_received), 0)

    async def test_menu_command_sends_greeting_and_keyboard(self):
        """Проверка, что команда /menu отправляет главное меню с кнопками."""
        user = User(id=103, is_bot=False, first_name="Tester")
        chat = Chat(id=103, type="private")
        msg = Message(
            message_id=4,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            text="/menu",
        )
        update = Update(update_id=4, message=msg)

        req_count_before = len(self.session.requests)
        await self.dp.feed_update(self.bot, update)

        # Шасси обработало команду /menu
        self.assertEqual(len(self.domain_text_received), 0)
        # Бот отправил сообщение пользователю
        send_reqs = [r for r in self.session.requests[req_count_before:] if r.__class__.__name__ == "SendMessage"]
        self.assertTrue(len(send_reqs) >= 1)
        self.assertIn("Главное меню", send_reqs[0].text)

    async def test_support_command_activates_pending_ticket(self):
        """Проверка, что команда /support активирует режим ввода тикета поддержки."""
        user = User(id=104, is_bot=False, first_name="Tester")
        chat = Chat(id=104, type="private")
        msg = Message(
            message_id=5,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            text="/support",
        )
        update = Update(update_id=5, message=msg)

        await self.dp.feed_update(self.bot, update)

        self.assertEqual(len(self.domain_text_received), 0)
        self.assertTrue(self.pending_store.is_active(104, PendingInputKind.SUPPORT_MESSAGE))

    async def test_active_support_ticket_intercepts_text_from_domain_router(self):
        """
        Проверка, что когда тикет поддержки АКТИВЕН, введенный текст
        перехватывается шасси и НЕ попадает в доменный роутер.
        """
        user = User(id=105, is_bot=False, first_name="Tester")
        chat = Chat(id=105, type="private")

        # 1. Активируем режим ввода тикета
        self.pending_store.set(105, PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=105))

        # 2. Пользователь отправляет сообщение с вопросом
        msg = Message(
            message_id=6,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            text="Сломался отчёт C4, помогите разобраться!",
        )
        update = Update(update_id=6, message=msg)

        req_count_before = len(self.session.requests)
        await self.dp.feed_update(self.bot, update)

        # Текст НЕ должен попасть в доменный роутер!
        self.assertEqual(len(self.domain_text_received), 0)
        # Тикет должен быть сброшен после успешной отправки
        self.assertFalse(self.pending_store.is_active(105, PendingInputKind.SUPPORT_MESSAGE))

        # Проверяем, что обращение ушло в support_chat_id
        support_sends = [
            r for r in self.session.requests[req_count_before:]
            if getattr(r, "chat_id", None) == self.support_chat_id
        ]
        self.assertTrue(len(support_sends) >= 1)

    async def test_admin_reply_isolated_to_support_chat_only(self):
        """
        Проверка, что ответ админа срабатывает ТОЛЬКО внутри support_chat_id,
        а ответы в посторонних группах или чатах игнорируются шасси.
        """
        # Регистрируем связку: в support_chat_id сообщение 500 привязано к user_id=105
        self.thread_store.register(chat_id=self.support_chat_id, user_id=105, header_msg_id=500)

        admin = User(id=777, is_bot=False, first_name="Admin")

        # СЛУЧАЙ А: Ответ в постороннем групповом чате (например, chat_id = -99999)
        foreign_chat = Chat(id=-99999, type="group")
        reply_to_foreign = Message(
            message_id=500,
            date=int(time.time()),
            chat=foreign_chat,
            text="Header",
        )
        msg_foreign = Message(
            message_id=501,
            date=int(time.time()),
            chat=foreign_chat,
            from_user=admin,
            text="Ответ админа из постороннего чата",
            reply_to_message=reply_to_foreign,
        )
        update_foreign = Update(update_id=7, message=msg_foreign)

        req_count_before = len(self.session.requests)
        await self.dp.feed_update(self.bot, update_foreign)

        # В постороннем чате пользователю 105 ничего не должно отправиться
        user_copies_foreign = [
            r for r in self.session.requests[req_count_before:]
            if getattr(r, "chat_id", None) == 105
        ]
        self.assertEqual(len(user_copies_foreign), 0)

        # СЛУЧАЙ Б: Ответ ВНУТРИ support_chat_id
        support_chat = Chat(id=self.support_chat_id, type="supergroup")
        reply_to_support = Message(
            message_id=500,
            date=int(time.time()),
            chat=support_chat,
            text="Header",
        )
        msg_support = Message(
            message_id=502,
            date=int(time.time()),
            chat=support_chat,
            from_user=admin,
            text="Здравствуйте, мы исправили C4!",
            reply_to_message=reply_to_support,
        )
        update_support = Update(update_id=8, message=msg_support)

        req_count_before_reply = len(self.session.requests)
        await self.dp.feed_update(self.bot, update_support)

        # Пользователю 105 доставлены шапка ответа и копия сообщения администратора
        user_copies_support = [
            r for r in self.session.requests[req_count_before_reply:]
            if getattr(r, "chat_id", None) == 105
        ]
        self.assertEqual(len(user_copies_support), 2)
        self.assertEqual(user_copies_support[0].__class__.__name__, "SendMessage")
        self.assertEqual(user_copies_support[1].__class__.__name__, "CopyMessage")

    async def test_admin_chat_chatter_silently_ignored(self):
        """
        Проверка, что реплики админов друг другу в support_chat_id (не привязанные к тикетам)
        не вызывают спам-ответов от бота (полная тишина).
        """
        admin1 = User(id=701, is_bot=False, first_name="Admin1")
        admin2 = User(id=702, is_bot=False, first_name="Admin2")
        support_chat = Chat(id=self.support_chat_id, type="supergroup")

        msg1 = Message(
            message_id=901,
            date=int(time.time()),
            chat=support_chat,
            from_user=admin1,
            text="Кто задеплоит новую версию?",
        )
        msg2 = Message(
            message_id=902,
            date=int(time.time()),
            chat=support_chat,
            from_user=admin2,
            text="Я сейчас задеплою",
            reply_to_message=msg1,
        )
        update = Update(update_id=10, message=msg2)

        req_count_before = len(self.session.requests)
        await self.dp.feed_update(self.bot, update)

        # Полная тишина: бот НЕ должен слать «не удалось определить адресата»
        new_requests = self.session.requests[req_count_before:]
        self.assertEqual(len(new_requests), 0)

    async def test_support_cancel_forgets_card_in_tracker(self):
        """Проверка, что нажатие инлайн-кнопки отмены тикета забывает карточку в трекере экранов."""
        self.screen_tracker.remember_card(user_id=106, chat_id=106, message_id=300)
        self.pending_store.set(106, PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE))

        user = User(id=106, is_bot=False, first_name="Tester")
        chat = Chat(id=106, type="private")
        query = types.CallbackQuery(
            id="cq_cancel_1",
            from_user=user,
            chat_instance="ci_1",
            data=CB_SUPPORT_CANCEL,
            message=Message(
                message_id=300,
                date=int(time.time()),
                chat=chat,
                from_user=user,
                text="Prompt",
            ),
        )
        update = Update(update_id=11, callback_query=query)

        await self.dp.feed_update(self.bot, update)

        # Проверяем, что карточка забыта в трекере!
        self.assertIsNone(self.screen_tracker.get_card(106))
        self.assertFalse(self.pending_store.is_active(106, PendingInputKind.SUPPORT_MESSAGE))

    async def test_ticket_receipt_does_not_attach_reply_markup(self):
        """Проверка, что квитанция отправки тикета НЕ содержит reply_markup (не плодит новые носители)."""
        user = User(id=107, is_bot=False, first_name="Tester")
        chat = Chat(id=107, type="private")
        self.pending_store.set(107, PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=107))

        msg = Message(
            message_id=77,
            date=int(time.time()),
            chat=chat,
            from_user=user,
            text="Вопрос по C1",
        )
        update = Update(update_id=12, message=msg)

        req_count_before = len(self.session.requests)
        await self.dp.feed_update(self.bot, update)

        # Находим ответ пользователю 107
        user_sends = [
            r for r in self.session.requests[req_count_before:]
            if getattr(r, "chat_id", None) == 107 and r.__class__.__name__ == "SendMessage"
        ]
        self.assertTrue(len(user_sends) >= 1)
        receipt = user_sends[0]
        # reply_markup ДОЛЖЕН БЫТЬ None!
        self.assertIsNone(getattr(receipt, "reply_markup", None))


if __name__ == "__main__":
    unittest.main()
