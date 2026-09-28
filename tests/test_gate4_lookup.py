"""Gate 4: ID или @username, отдельный поиск админки, честный username."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot_chassis.admin.lookup import (
    FIND_CANCELLED,
    FIND_PROMPT,
    admin_lookup_is_waiting,
    begin_admin_lookup,
    cancel_admin_lookup,
    reset_admin_lookups,
)
from bot_chassis.admin.broadcast import (
    is_awaiting_broadcast_text,
    reset_broadcast_sessions,
)
from bot_chassis.admin.router import CB_BROADCAST, CB_FIND, create_admin_router
from bot_chassis.config import BotChassisConfig
from bot_chassis.followup import PendingInput, PendingInputKind, PendingInputStore
from bot_chassis.storage import create_storage


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        pass

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


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="N")


class TestUserLookup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "lookup.db")
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            audit_chat_id=-100,
        )
        self.storage = await create_storage(self.config)
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        reset_admin_lookups()
        reset_broadcast_sessions()
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.dp = Dispatcher()
        self.dp.include_router(create_admin_router("bot_a", self.storage, self.config))

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()
        reset_admin_lookups()
        reset_broadcast_sessions()

    def _texts(self, chat_id: int) -> list[str]:
        return [
            item.text
            for item in self.session.requests
            if item.__class__.__name__ == "SendMessage" and item.chat_id == chat_id
        ]

    async def _text(self, user_id: int, text: str, update_id: int) -> None:
        message = Message(
            message_id=update_id,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=_user(user_id),
            text=text,
        )
        await self.dp.feed_update(self.bot, Update(update_id=update_id, message=message))

    async def _callback(self, user_id: int, data: str, update_id: int) -> None:
        panel = Message(message_id=40, date=1, chat=Chat(id=user_id, type="private"), text="admin")
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

    async def test_username_clears_releases_and_stays_inside_tenant(self) -> None:
        await self.storage.users.upsert_user("bot_a", 1, username="@Ann")
        await self.storage.users.upsert_user("bot_a", 2, username="Other")
        other = BotChassisConfig(bot_id="bot_b", db_path=self.db_path)
        other_storage = await create_storage(other)
        await other_storage.users.upsert_user("bot_b", 1, username="Ann")

        self.assertEqual((await self.storage.users.get_user("bot_a", 1)).username, "Ann")
        await self.storage.users.upsert_user("bot_a", 1)
        self.assertEqual((await self.storage.users.get_user("bot_a", 1)).username, "Ann")

        await self.storage.users.record_telegram_visit("bot_a", 2, None, "N", None, None, "en")
        self.assertIsNone((await self.storage.users.get_user("bot_a", 2)).username)

        await self.storage.users.record_telegram_visit("bot_a", 3, "@ann", "N", None, "en", "en")
        self.assertEqual((await self.storage.users.get_user("bot_a", 3)).username, "ann")
        self.assertIsNone((await self.storage.users.get_user("bot_a", 1)).username)
        self.assertEqual((await other_storage.users.get_user("bot_b", 1)).username, "Ann")

        matches = await self.storage.users.find_by_username("bot_a", "ANN")
        self.assertEqual([item.user_id for item in matches], [3])

    async def test_commands_accept_id_and_username_without_picking_duplicates(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="neo")
        await self.storage.users.upsert_user("bot_a", 17, username="solo")
        await self._text(14, "/ban @NEO spam", 1)
        self.assertTrue((await self.storage.users.get_user("bot_a", 16)).is_banned)
        await self._text(14, "/unban neo", 2)
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_banned)
        await self._text(14, "/shadowban @solo 1", 3)
        self.assertTrue((await self.storage.users.get_user("bot_a", 17)).is_shadow_banned)
        await self._text(100, "/grant @neo admin", 4)
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 16, ("admin",)))
        await self._text(100, "/gift solo 5", 5)
        await self._text(14, "/user @missing", 6)
        self.assertIn("Пользователь не найден", self._texts(14))

        def _dup(conn) -> None:
            conn.execute("UPDATE users SET username = 'neo' WHERE bot_id = 'bot_a' AND user_id IN (16, 17)")

        await self.storage.engine.run(_dup)
        self.session.requests.clear()
        await self._text(14, "/ban @neo", 7)
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_banned)
        self.assertFalse((await self.storage.users.get_user("bot_a", 17)).is_banned)
        listed = "\n".join(self._texts(14))
        self.assertIn("16 @neo", listed)
        self.assertIn("17 @neo", listed)
        self.assertIn("Уточните числовой ID.", listed)

    async def test_lookup_opens_dossier_and_cancel_keeps_other_waits(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="neo")
        pending = PendingInputStore()
        pending.set(14, PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=14))

        await self._callback(14, CB_FIND, 1)
        self.assertIn(FIND_PROMPT, self._texts(14))
        self.assertTrue(admin_lookup_is_waiting("bot_a", 14))
        self.assertEqual(pending.get(14).kind, PendingInputKind.SUPPORT_MESSAGE)

        self.session.requests.clear()
        await self._text(14, "/cancel", 2)
        self.assertIn(FIND_CANCELLED, self._texts(14))
        self.assertFalse(admin_lookup_is_waiting("bot_a", 14))
        self.assertIsNotNone(pending.get(14))

        await self._callback(14, CB_FIND, 3)
        self.session.requests.clear()
        await self._text(14, "@neo", 4)
        dossier = self._texts(14)
        self.assertTrue(any("ID: 16" in text for text in dossier))
        self.assertFalse(admin_lookup_is_waiting("bot_a", 14))
        self.assertEqual(pending.get(14).kind, PendingInputKind.SUPPORT_MESSAGE)

    async def test_lookup_and_broadcast_waits_are_scoped_by_bot(self) -> None:
        begin_admin_lookup("bot_a", 14)
        self.assertTrue(admin_lookup_is_waiting("bot_a", 14))
        self.assertFalse(admin_lookup_is_waiting("bot_b", 14))

        begin_admin_lookup("bot_b", 14)
        cancel_admin_lookup("bot_a", 14)
        self.assertFalse(admin_lookup_is_waiting("bot_a", 14))
        self.assertTrue(admin_lookup_is_waiting("bot_b", 14))
        cancel_admin_lookup("bot_b", 14)

        await self._callback(14, CB_BROADCAST, 10)
        self.assertTrue(is_awaiting_broadcast_text("bot_a", 14))
        self.assertFalse(is_awaiting_broadcast_text("bot_b", 14))

        config_b = BotChassisConfig(
            bot_id="bot_b",
            db_path=self.db_path,
            superadmin_ids=(200,),
            audit_chat_id=-200,
        )
        storage_b = await create_storage(config_b)
        await storage_b.roles.grant_role("bot_b", 14, "admin", granted_by=200)
        dp_b = Dispatcher()
        dp_b.include_router(create_admin_router("bot_b", storage_b, config_b))
        panel = Message(message_id=40, date=1, chat=Chat(id=14, type="private"), text="admin")
        await dp_b.feed_update(
            self.bot,
            Update(
                update_id=11,
                callback_query=CallbackQuery(
                    id="11",
                    from_user=_user(14),
                    chat_instance="x",
                    data=CB_FIND,
                    message=panel,
                ),
            ),
        )
        self.assertTrue(admin_lookup_is_waiting("bot_b", 14))
        self.assertTrue(is_awaiting_broadcast_text("bot_a", 14))
        self.assertIn(FIND_PROMPT, self._texts(14))
