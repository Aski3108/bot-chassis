"""Gate 9: role-dependent admin screens, floating panel, permanent reports."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot_chassis.admin.lookup import FIND_PROMPT, reset_admin_lookups
from bot_chassis.admin.broadcast import reset_broadcast_sessions
from bot_chassis.admin.router import CB_EXPORT, CB_FIND, SUPERADMIN_ONLY, create_admin_router
from bot_chassis.admin.screens import (
    CB_BACK,
    CB_GO_BCAST,
    CB_GO_EXPORT,
    CB_GO_MAINT,
    CB_GO_RESTART,
    CB_GO_STATS,
    AdminScreenTracker,
)
from bot_chassis.config import BotChassisConfig
from bot_chassis.policies import BackupPolicy, ReportingPolicy
from bot_chassis.storage import create_storage


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
                message_id=getattr(method, "message_id", None) or len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0) or 14, type="private"),
                text=getattr(method, "text", "") or "",
            )
        return True

    async def stream_content(self, url: str, headers=None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="N")


class TestGate9AdminScreens(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "admin.db")
        self.catalog = os.path.join(self._tmp.name, "snap")
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            audit_chat_id=-100,
        )
        self.storage = await create_storage(self.config)
        reset_broadcast_sessions()
        reset_admin_lookups()
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        await self.storage.users.upsert_user("bot_a", 15)
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.dp = Dispatcher()
        self.dp.include_router(
            create_admin_router(
                "bot_a",
                self.storage,
                self.config,
                backup_policy=BackupPolicy(directory=self.catalog),
                reporting_policy=ReportingPolicy(),
            )
        )

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    def _named(self, name: str):
        return [item for item in self.session.requests if item.__class__.__name__ == name]

    async def _command(self, user_id: int, update_id: int) -> None:
        await self.dp.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=1,
                    chat=Chat(id=user_id, type="private"),
                    from_user=_user(user_id),
                    text="/admin",
                ),
            ),
        )

    async def _callback(self, user_id: int, data: str, update_id: int, message_id: int = 50) -> None:
        panel = Message(
            message_id=message_id,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=_user(user_id),
            text="admin",
        )
        await self.dp.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=str(update_id),
                    from_user=_user(user_id),
                    chat_instance="x",
                    data=data,
                    message=panel,
                ),
            ),
        )

    async def test_staff_home_hides_root_actions_and_stats_navigates(self) -> None:
        await self._command(14, 1)
        home = self._named("SendMessage")[0]
        callbacks = [button.callback_data for row in home.reply_markup.inline_keyboard for button in row]
        self.assertEqual(callbacks, [CB_GO_STATS, CB_FIND, CB_GO_MAINT])
        self.assertIn("Планировщик: включён", home.text)
        self.assertIn("backup 04:00", home.text)

        self.session.requests.clear()
        await self._callback(14, CB_GO_STATS, 2)
        stats = self._named("EditMessageText")[0]
        self.assertIn("Статистика", stats.text)
        self.assertIn("Бан:", stats.text)
        nav = [button.callback_data for row in stats.reply_markup.inline_keyboard for button in row]
        self.assertIn(CB_BACK, nav)
        self.assertIn("adm_home", nav)

        self.session.requests.clear()
        await self._callback(14, CB_BACK, 3)
        self.assertIn("Админка", self._named("EditMessageText")[0].text)

        self.session.requests.clear()
        await self._callback(14, CB_GO_EXPORT, 4)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, SUPERADMIN_ONLY)
        self.assertFalse(self._named("SendDocument"))

        self.session.requests.clear()
        await self._callback(14, CB_GO_BCAST, 45)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, SUPERADMIN_ONLY)

        self.session.requests.clear()
        await self._callback(14, CB_GO_RESTART, 5)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, SUPERADMIN_ONLY)

    async def test_root_restart_hidden_without_port(self) -> None:
        await self._callback(100, CB_GO_RESTART, 1)
        answers = self._named("AnswerCallbackQuery")
        self.assertTrue(answers)
        self.assertIn("не подключено", answers[0].text.lower())
        self.assertFalse(self._named("EditMessageText"))

    async def test_repeat_admin_replaces_panel_and_survives_deleted_message(self) -> None:
        tracker = AdminScreenTracker()
        dp = Dispatcher()
        dp.include_router(create_admin_router("bot_a", self.storage, self.config, screens=tracker))
        await dp.feed_update(
            self.bot,
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=1,
                    chat=Chat(id=14, type="private"),
                    from_user=_user(14),
                    text="/admin",
                ),
            ),
        )
        first = tracker.get("bot_a", 14)
        self.assertIsNotNone(first)
        self.session.requests.clear()
        await dp.feed_update(
            self.bot,
            Update(
                update_id=2,
                message=Message(
                    message_id=2,
                    date=1,
                    chat=Chat(id=14, type="private"),
                    from_user=_user(14),
                    text="/admin",
                ),
            ),
        )
        second = tracker.get("bot_a", 14)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertEqual(len(tracker._panels), 1)

        self.session.requests.clear()
        from aiogram.types import InaccessibleMessage

        gone = InaccessibleMessage(chat=Chat(id=14, type="private"), message_id=99, date=0)
        await dp.feed_update(
            self.bot,
            Update(
                update_id=3,
                callback_query=CallbackQuery(
                    id="3",
                    from_user=_user(14),
                    chat_instance="x",
                    data=CB_GO_STATS,
                    message=gone,
                ),
            ),
        )
        self.assertTrue(any("Статистика" in (item.text or "") for item in self._named("SendMessage")))

    async def test_find_and_export_screens_keep_one_panel(self) -> None:
        await self._callback(14, CB_FIND, 1)
        edited = self._named("EditMessageText")
        self.assertTrue(any(FIND_PROMPT in (item.text or "") for item in edited))
        self.session.requests.clear()
        await self._callback(100, CB_GO_EXPORT, 2)
        export = self._named("EditMessageText")[0]
        self.assertIn("xlsx", export.text.lower())
        self.assertIn(CB_EXPORT, [button.callback_data for row in export.reply_markup.inline_keyboard for button in row])
        self.session.requests.clear()
        await self._callback(100, CB_GO_BCAST, 3)
        bcast = self._named("EditMessageText")[0]
        self.assertIn("Рассылка", bcast.text)
        self.assertIn(
            "adm_bcast",
            [button.callback_data for row in bcast.reply_markup.inline_keyboard for button in row],
        )

    async def test_lookup_result_retires_prompt_panel(self) -> None:
        await self._callback(14, CB_FIND, 1, message_id=50)
        self.session.requests.clear()
        await self.dp.feed_update(
            self.bot,
            Update(
                update_id=2,
                message=Message(
                    message_id=2,
                    date=1,
                    chat=Chat(id=14, type="private"),
                    from_user=_user(14),
                    text="15",
                ),
            ),
        )
        retired = self._named("EditMessageReplyMarkup")
        self.assertTrue(any(item.message_id == 50 and item.reply_markup is None for item in retired))
        dossiers = [item for item in self._named("SendMessage") if "Досье пользователя" in (item.text or "")]
        self.assertEqual(len(dossiers), 1)

    async def test_user_command_retires_existing_panel(self) -> None:
        await self._command(14, 1)
        active_panel = 1  # fake session returns len(requests) as the sent message ID
        self.session.requests.clear()
        await self.dp.feed_update(
            self.bot,
            Update(
                update_id=2,
                message=Message(
                    message_id=2,
                    date=1,
                    chat=Chat(id=14, type="private"),
                    from_user=_user(14),
                    text="/user 15",
                ),
            ),
        )
        retired = self._named("EditMessageReplyMarkup")
        self.assertTrue(
            any(item.message_id == active_panel and item.reply_markup is None for item in retired)
        )
        dossiers = [item for item in self._named("SendMessage") if "Досье пользователя" in (item.text or "")]
        self.assertEqual(len(dossiers), 1)


if __name__ == "__main__":
    unittest.main()
