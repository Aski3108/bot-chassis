"""Release 2.0 Gate A0: общее меню, экран БД и throttled root guard."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot_chassis.admin.broadcast import (
    CB_BROADCAST_CANCEL,
    CB_BROADCAST_GO,
    CB_BROADCAST_STOP,
    is_awaiting_broadcast_text,
    reset_broadcast_sessions,
)
from bot_chassis.admin.lookup import reset_admin_lookups
from bot_chassis.admin.process import (
    CB_RST_ALL,
    CB_RST_NO,
    CB_RST_PREFIX_OK,
    CB_RST_PREFIX_ONE,
    reset_process_intents,
)
from bot_chassis.admin.router import (
    CB_BROADCAST,
    CB_EXPORT,
    CB_FIND,
    CB_HOME,
    SECURITY_ALERT_TTL_SECONDS,
    _SECURITY_ALERT_THROTTLE,
    create_admin_router,
)
from bot_chassis.admin.screens import (
    CB_DO_BACKUP,
    CB_DO_MAINT,
    CB_GO_BCAST,
    CB_GO_DB,
    CB_GO_MAINT,
    CB_GO_RESTART,
    CB_GO_STATS,
)
from bot_chassis.config import BotChassisConfig
from bot_chassis.policies import BackupPolicy
from bot_chassis.ports.process_control import ProcessOperationResult, ProcessTarget
from bot_chassis.storage import create_storage

ACCESS_DENIED = "Access Denied"
BASE_ROWS = (
    ("📊 Статистика", CB_GO_STATS),
    ("🔍 Найти пользователя", CB_FIND),
    ("📢 Рассылка", CB_GO_BCAST),
    ("💾 База данных", CB_GO_DB),
    ("⚙️ Рубильник", CB_GO_MAINT),
)
RESTART_ROW = ("🔄 Рестарт бота", CB_GO_RESTART)
DB_ROWS = (
    ("📥 Выгрузка пользователей (.xlsx)", CB_EXPORT),
    ("💾 Бэкап базы данных (.db)", CB_DO_BACKUP),
    ("« Назад", CB_HOME),
)
DB_MENU_TEXT = (
    "💾 <b>Управление базой данных</b>\n"
    "\n"
    "Выберите действие:\n"
    "• Выгрузка пользователей — файл Excel (.xlsx) с гиперссылками на профили.\n"
    "• Бэкап базы данных (.db) — бинарный файл SQLite базы данных проекта.\n"
    "• Список пользователей — просмотр всей базы прямо в Telegram."
)


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


class _Port:
    def __init__(self) -> None:
        self.restarts: list[str] = []
        self.listed = 0

    async def list_targets(self):
        self.listed += 1
        return [ProcessTarget("alpha", "Alpha", status="up")]

    async def restart(self, target_id: str) -> ProcessOperationResult:
        self.restarts.append(target_id)
        return ProcessOperationResult(operation_id="op", target_id=target_id, status="ok")


def _user(user_id: int, username: str | None = None) -> User:
    return User(id=user_id, is_bot=False, first_name="N", username=username)


def _rows(markup) -> list[tuple[str, str]]:
    return [
        (button.text, button.callback_data)
        for row in markup.inline_keyboard
        for button in row
    ]


class TestAdminV2A0(unittest.IsolatedAsyncioTestCase):
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
        reset_process_intents()
        _SECURITY_ALERT_THROTTLE.clear()
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        await self.storage.users.upsert_user("bot_a", 15)
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.port = _Port()
        self.dp = Dispatcher()
        self.dp.include_router(
            create_admin_router(
                "bot_a",
                self.storage,
                self.config,
                backup_policy=BackupPolicy(directory=self.catalog),
                process_control=self.port,
            )
        )

    async def asyncTearDown(self) -> None:
        _SECURITY_ALERT_THROTTLE.clear()
        await self.bot.session.close()
        self._tmp.cleanup()

    def _named(self, name: str):
        return [item for item in self.session.requests if item.__class__.__name__ == name]

    def _audits(self):
        return [
            item
            for item in self._named("SendMessage")
            if item.chat_id == -100 and "несанкционированного доступа" in (item.text or "")
        ]

    async def _command(self, user_id: int, update_id: int, dispatcher: Dispatcher | None = None) -> None:
        await (dispatcher or self.dp).feed_update(
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

    async def _callback(
        self,
        user_id: int,
        data: str,
        update_id: int,
        *,
        username: str | None = None,
        dispatcher: Dispatcher | None = None,
    ) -> None:
        panel = Message(
            message_id=50,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=_user(user_id, username=username),
            text="admin",
        )
        await (dispatcher or self.dp).feed_update(
            self.bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=str(update_id),
                    from_user=_user(user_id, username=username),
                    chat_instance="x",
                    data=data,
                    message=panel,
                ),
            ),
        )

    async def test_admin_home_has_exact_labels_and_same_base_rows(self) -> None:
        plain = Dispatcher()
        plain.include_router(create_admin_router("bot_a", self.storage, self.config))
        await self._command(14, 1, plain)
        await self._command(100, 2, plain)
        homes = [
            item
            for item in self._named("SendMessage")
            if "Админка" in (item.text or "")
        ]
        self.assertEqual(len(homes), 2)
        staff_rows = _rows(homes[0].reply_markup)
        root_rows = _rows(homes[1].reply_markup)
        self.assertEqual(staff_rows, list(BASE_ROWS))
        self.assertEqual(root_rows, list(BASE_ROWS))
        self.assertNotIn(RESTART_ROW, staff_rows)
        self.assertNotIn("Команды:", homes[0].text)
        self.assertNotIn("Команды:", homes[1].text)
        self.assertNotIn("/export", homes[0].text)
        self.assertNotIn("/export", homes[1].text)

        class Extra:
            def home_rows(self):
                return [[("♻️ Restart adhd", "adm_ops:restart:adhd")]]

            async def handle_callback(self, call):
                return True

        self.session.requests.clear()
        wired = Dispatcher()
        wired.include_router(
            create_admin_router(
                "bot_a",
                self.storage,
                self.config,
                extra_actions=Extra(),
                process_control=self.port,
            )
        )
        await self._command(14, 3, wired)
        await self._command(100, 4, wired)
        wired_homes = [
            item
            for item in self._named("SendMessage")
            if "Админка" in (item.text or "")
        ]
        self.assertEqual(_rows(wired_homes[0].reply_markup), [*BASE_ROWS, RESTART_ROW])
        self.assertEqual(
            _rows(wired_homes[1].reply_markup),
            [*BASE_ROWS, RESTART_ROW, ("♻️ Restart adhd", "adm_ops:restart:adhd")],
        )

    async def test_root_guard_denies_forged_callback_without_side_effect(self) -> None:
        forged = [
            CB_GO_DB,
            CB_EXPORT,
            CB_DO_BACKUP,
            CB_BROADCAST,
            CB_BROADCAST_GO,
            CB_BROADCAST_CANCEL,
            CB_BROADCAST_STOP,
            CB_GO_RESTART,
            CB_RST_ALL,
            CB_RST_PREFIX_ONE + "alpha",
            CB_RST_NO,
            CB_RST_PREFIX_OK + "deadbeef",
        ]
        for index, data in enumerate(forged, start=1):
            self.session.requests.clear()
            await self._callback(14, data, index)
            answers = self._named("AnswerCallbackQuery")
            self.assertEqual(len(answers), 1, data)
            self.assertEqual(answers[0].text, ACCESS_DENIED, data)
            self.assertTrue(answers[0].show_alert, data)
        self.assertFalse(self._named("SendDocument"))
        self.assertFalse(is_awaiting_broadcast_text("bot_a", 14))
        self.assertEqual(self.port.restarts, [])
        self.assertEqual(self.port.listed, 0)
        edited = "\n".join(item.text or "" for item in self._named("EditMessageText"))
        self.assertNotIn("Перезапустить", edited)
        self.assertNotIn("Управление базой данных", edited)

        self.session.requests.clear()
        _SECURITY_ALERT_THROTTLE.clear()
        with patch(
            "bot_chassis.admin.router.send_admin_audit",
            side_effect=RuntimeError("audit down"),
        ):
            await self._callback(14, CB_EXPORT, 90)
        answers = self._named("AnswerCallbackQuery")
        self.assertEqual([item.text for item in answers], [ACCESS_DENIED])
        self.assertFalse(self._named("SendDocument"))
        self.assertFalse(is_awaiting_broadcast_text("bot_a", 14))

    async def test_security_alert_exact_html(self) -> None:
        await self._callback(14, CB_GO_BCAST, 1, username="a<b>")
        await self._callback(14, CB_GO_DB, 2)
        audits = self._audits()
        self.assertEqual(
            [item.text for item in audits],
            [
                "🚨 <b>Попытка несанкционированного доступа</b>: "
                "админ @a&lt;b&gt; (ID: <code>14</code>) нажал <b>[Рассылка]</b>",
                "🚨 <b>Попытка несанкционированного доступа</b>: "
                "админ без username (ID: <code>14</code>) нажал <b>[База данных]</b>",
            ],
        )
        self.assertEqual(
            [item.parse_mode for item in audits],
            ["HTML", "HTML"],
        )

    async def test_security_alert_parallel_clicks_emit_one_audit(self) -> None:
        original = self.storage.roles.has_any_role
        waiting: list[int] = []
        release = asyncio.Event()

        async def gated(bot_id: str, user_id: int, roles):
            if roles == ("superadmin",):
                waiting.append(user_id)
                if len(waiting) >= 2:
                    release.set()
                await release.wait()
            return await original(bot_id, user_id, roles)

        self.storage.roles.has_any_role = gated
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    self._callback(14, CB_GO_DB, 1),
                    self._callback(14, CB_GO_DB, 2),
                ),
                timeout=3,
            )
        finally:
            self.storage.roles.has_any_role = original
        answers = self._named("AnswerCallbackQuery")
        self.assertEqual(len(answers), 2)
        self.assertTrue(all(item.text == ACCESS_DENIED and item.show_alert for item in answers))
        self.assertEqual(len(self._audits()), 1)
        self.assertFalse(self._named("EditMessageText"))

    async def test_security_alert_is_throttled_per_bot_actor_action(self) -> None:
        clock = {"now": 1_000.0}

        def monotonic() -> float:
            return clock["now"]

        _SECURITY_ALERT_THROTTLE[("bot_z", 1, "old")] = clock["now"] - SECURITY_ALERT_TTL_SECONDS
        _SECURITY_ALERT_THROTTLE[("bot_z", 1, "fresh")] = clock["now"]
        with patch("bot_chassis.admin.router.time.monotonic", monotonic):
            for index in range(1, 11):
                await self._callback(14, CB_GO_DB, index)
            self.assertEqual(len(self._named("AnswerCallbackQuery")), 10)
            self.assertEqual(len(self._audits()), 1)
            self.assertNotIn(("bot_z", 1, "old"), _SECURITY_ALERT_THROTTLE)
            self.assertIn(("bot_z", 1, "fresh"), _SECURITY_ALERT_THROTTLE)

            clock["now"] = 1_000.0 + SECURITY_ALERT_TTL_SECONDS - 0.1
            await self._callback(14, CB_GO_DB, 11)
            self.assertEqual(len(self._audits()), 1)

            clock["now"] = 1_000.0 + SECURITY_ALERT_TTL_SECONDS
            await self._callback(14, CB_GO_DB, 12)
            self.assertEqual(len(self._audits()), 2)

            await self._callback(14, CB_EXPORT, 13)
            self.assertEqual(len(self._audits()), 3)

            await self.storage.roles.grant_role("bot_b", 14, "admin", granted_by=100)
            other = Dispatcher()
            other.include_router(create_admin_router("bot_b", self.storage, self.config))
            await self._callback(14, CB_GO_DB, 14, dispatcher=other)
            self.assertEqual(len(self._audits()), 4)
            self.assertIn(("bot_a", 14, CB_GO_DB), _SECURITY_ALERT_THROTTLE)
            self.assertIn(("bot_b", 14, CB_GO_DB), _SECURITY_ALERT_THROTTLE)

    async def test_maintenance_keeps_toggle_and_only_one_back_button(self) -> None:
        await self._callback(14, CB_GO_MAINT, 1)
        screen = self._named("EditMessageText")[0]
        self.assertEqual(
            _rows(screen.reply_markup),
            [("Опустить рубильник", CB_DO_MAINT), ("« Назад", CB_HOME)],
        )
        self.assertNotIn("В главное меню", [text for text, _data in _rows(screen.reply_markup)])

        await self.storage.bot_settings.set_maintenance_status("bot_a", True, reason=None, updated_by=100)
        self.session.requests.clear()
        await self._callback(14, CB_GO_MAINT, 2)
        screen = self._named("EditMessageText")[0]
        self.assertEqual(
            _rows(screen.reply_markup),
            [("Снять рубильник", CB_DO_MAINT), ("« Назад", CB_HOME)],
        )

    async def test_db_actions_have_no_intermediate_screen(self) -> None:
        await self._callback(100, CB_GO_DB, 1)
        screen = self._named("EditMessageText")[0]
        self.assertEqual(screen.text, DB_MENU_TEXT)
        self.assertEqual(_rows(screen.reply_markup), list(DB_ROWS))
        self.assertNotIn("Список пользователей", [text for text, _data in _rows(screen.reply_markup)])
        self.assertNotIn("Скачать Excel", screen.text)

        self.session.requests.clear()
        await self._callback(100, CB_EXPORT, 2)
        answers = self._named("AnswerCallbackQuery")
        self.assertEqual([item.text for item in answers], ["Формирую файл..."])
        documents = self._named("SendDocument")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].chat_id, 100)
        self.assertFalse(self._named("EditMessageText"))
        self.assertFalse(any("Админка" in (item.text or "") for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._callback(100, CB_DO_BACKUP, 3)
        self.assertEqual(
            [item.text for item in self._named("AnswerCallbackQuery")],
            ["Готовлю снимок..."],
        )
        self.assertEqual(len(self._named("SendDocument")), 1)
        self.assertFalse(self._named("EditMessageText"))
        self.assertFalse(any("Админка" in (item.text or "") for item in self._named("SendMessage")))


if __name__ == "__main__":
    unittest.main()
