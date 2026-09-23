"""
Юнит-тесты универсального костяка бота (bot_core).
Проверяют клавиатуры, дедупликацию задач, хранилище ввода и обработчики моста поддержки.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot_chassis.contracts import (
    BTN_CABINET,
    BTN_INFO,
    BTN_SUPPORT,
    is_main_menu_button,
)
from bot_chassis.keyboards import (
    build_main_menu_keyboard,
    build_cabinet_inline_keyboard,
    build_info_inline_keyboard,
    build_support_inline_keyboard,
)
from bot_chassis.followup import (
    InMemoryPendingInputStore,
    PendingInput,
    PendingInputKind,
)
from bot_chassis.dispatcher import ActiveTaskTracker
from bot_chassis.lifecycle import edit_or_send
from bot_chassis.support_bridge import (
    register_support_thread,
    resolve_user_by_admin_reply,
    send_user_report_to_support,
    deliver_support_reply_to_user,
)


class TestBotChassis(unittest.TestCase):
    def test_main_menu_keyboard_attributes(self):
        """Проверка Telegram Bot API флагов для неисчезающей клавиатуры."""
        kb = build_main_menu_keyboard()
        self.assertTrue(kb.is_persistent)
        self.assertTrue(kb.resize_keyboard)
        self.assertFalse(kb.one_time_keyboard)
        self.assertEqual(kb.input_field_placeholder, "Выберите действие в меню")
        self.assertEqual(len(kb.keyboard), 2)
        self.assertEqual(kb.keyboard[0][0].text, BTN_CABINET)
        self.assertEqual(kb.keyboard[1][0].text, BTN_INFO)
        self.assertEqual(kb.keyboard[1][1].text, BTN_SUPPORT)

    def test_menu_button_contract_matching(self):
        """Проверка распознавания кнопок меню (включая алиасы для сброса ввода)."""
        self.assertTrue(is_main_menu_button(BTN_CABINET))
        self.assertTrue(is_main_menu_button(BTN_INFO))
        self.assertTrue(is_main_menu_button(BTN_SUPPORT))
        self.assertTrue(is_main_menu_button("Личный кабинет"))
        self.assertTrue(is_main_menu_button("Report"))
        self.assertFalse(is_main_menu_button("Привет, как дела?"))
        self.assertFalse(is_main_menu_button(None))

    def test_pending_input_store(self):
        """Проверка легковесного хранилища состояний ожидания ввода."""
        store = InMemoryPendingInputStore()
        self.assertIsNone(store.get(12345))
        
        pi = PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=100)
        store.set(12345, pi)
        self.assertEqual(store.get(12345).kind, PendingInputKind.SUPPORT_MESSAGE)
        self.assertTrue(store.is_active(12345, PendingInputKind.SUPPORT_MESSAGE))
        self.assertFalse(store.is_active(12345, PendingInputKind.SUPPORT_REPLY))

        cleared = store.clear(12345)
        self.assertEqual(cleared, pi)
        self.assertIsNone(store.get(12345))

    def test_active_task_tracker_deduplication(self):
        """Проверка дедупликации повторных кликов и отмены устаревших задач."""
        tracker = ActiveTaskTracker()
        task1 = Mock()
        task1.done.return_value = False
        task1.cancel = Mock()

        # Первый клик -> разрешено
        self.assertTrue(tracker.should_process(user_id=1, route_name="menu:info", current_task=task1))

        # Повторный клик на ту же кнопку пока task1 не завершен -> отклонено (дедупликация)
        task2 = Mock()
        task2.done.return_value = False
        self.assertFalse(tracker.should_process(user_id=1, route_name="menu:info", current_task=task2))
        task1.cancel.assert_not_called()

        # Клик на другую кнопку меню -> старый таск отменяется, новый разрешается
        task3 = Mock()
        task3.done.return_value = False
        self.assertTrue(tracker.should_process(user_id=1, route_name="menu:cabinet", current_task=task3))
        task1.cancel.assert_called_once()

    def test_support_bridge_thread_mapping(self):
        """Проверка маппинга переписки поддержки по reply_message_id."""
        register_support_thread(admin_msg_id=999, user_id=777)
        self.assertEqual(resolve_user_by_admin_reply(999), 777)
        self.assertIsNone(resolve_user_by_admin_reply(111))


class TestBotChassisAsync(unittest.IsolatedAsyncioTestCase):
    async def test_edit_or_send_catches_message_not_modified(self):
        """Проверка перехвата ошибки TelegramBadRequest 'message is not modified'."""
        msg = Mock()
        msg.edit_text = AsyncMock(side_effect=TelegramBadRequest(method=Mock(), message="Bad Request: message is not modified"))
        msg.answer = AsyncMock()

        res = await edit_or_send(msg, "Same text")
        self.assertEqual(res, msg)
        msg.answer.assert_not_called()

    async def test_deliver_support_reply_handles_user_block(self):
        """Проверка корректной обработки 403 (бот заблокирован пользователем)."""
        admin_msg = Mock()
        admin_msg.reply_to_message = Mock(message_id=555)
        admin_msg.chat = Mock(id=10)
        admin_msg.message_id = 20

        register_support_thread(555, user_id=888)

        bot = Mock()
        bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(method=Mock(), message="Forbidden: bot was blocked by the user"))

        admin_msg.bot = bot
        success, status = await deliver_support_reply_to_user(bot, admin_msg)
        self.assertFalse(success)
        self.assertIn("заблокировал", status)


if __name__ == "__main__":
    unittest.main()
