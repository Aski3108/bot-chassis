"""Release 2.0 Gate A0: общее меню, экран БД и throttled root guard."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
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
    _dossier,
    _parse_sanction_callback,
    _sanctions_keyboard,
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
from bot_chassis.policies import BACKUP_JOB_KEY, BackupPolicy
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


_FROZEN_UTC = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
_TODAY_START = "2026-10-12 19:00:00"
_SEEN_EDGE = "2026-10-06 12:00:00"
_SEEN_BEFORE_EDGE = "2026-10-06 11:59:59"


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _FROZEN_UTC.replace(tzinfo=None)
        return _FROZEN_UTC.astimezone(tz)


class TestAdminV2A6(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "admin.db")
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
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.telegram_bot_id = int(self.bot.id)
        self.dp = Dispatcher()
        self.dp.include_router(create_admin_router("bot_a", self.storage, self.config))

        def _age(conn) -> None:
            conn.execute(
                "UPDATE users SET created_at = '2020-01-01 00:00:00' WHERE bot_id = 'bot_a'"
            )

        await self.storage.engine.run(_age)

    async def asyncTearDown(self) -> None:
        _SECURITY_ALERT_THROTTLE.clear()
        await self.bot.session.close()
        self._tmp.cleanup()

    def _named(self, name: str):
        return [item for item in self.session.requests if item.__class__.__name__ == name]

    async def _callback(self, user_id: int, data: str, update_id: int) -> None:
        panel = Message(
            message_id=50,
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

    async def _stats(self, update_id: int = 1) -> str:
        with patch("bot_chassis.admin.router.datetime", _FrozenDateTime):
            await self._callback(14, CB_GO_STATS, update_id)
        return self._named("EditMessageText")[-1].text

    async def _seen(self, user_id: int, telegram_bot_id: int, last_seen: str) -> None:
        await self.storage.users.upsert_user("bot_a", user_id)

        def _op(conn) -> None:
            conn.execute(
                """
                INSERT INTO user_bot_statuses (
                    bot_id, user_id, origin_bot_id, telegram_bot_id, status,
                    first_seen_at, last_seen_at, status_changed_at
                ) VALUES ('bot_a', ?, 'bot_a', ?, 'active', ?, ?, ?)
                """,
                (user_id, telegram_bot_id, last_seen, last_seen, last_seen),
            )

        await self.storage.engine.run(_op)

    async def _pay(
        self,
        user_id: int,
        payment_id: str,
        amount: int,
        created_at: str,
        *,
        provider: str = "telegram_stars",
        currency: str = "XTR",
        bot_id: str = "bot_a",
    ) -> None:
        await self.storage.users.upsert_user(bot_id, user_id)
        await self.storage.transactions.record_successful_payment(
            bot_id,
            user_id,
            "vip",
            amount,
            payment_id,
            provider=provider,
            currency=currency,
            payment_id=payment_id,
        )

        def _op(conn) -> None:
            conn.execute(
                "UPDATE transactions SET created_at = ? WHERE bot_id = ? AND payment_id = ?",
                (created_at, bot_id, payment_id),
            )

        await self.storage.engine.run(_op)

    async def test_dashboard_uses_current_bot_last_seen_for_active_7_days(self) -> None:
        await self._seen(201, self.telegram_bot_id, _SEEN_EDGE)
        await self._seen(202, self.telegram_bot_id, _SEEN_BEFORE_EDGE)
        await self._seen(203, 999, "2026-10-13 12:00:00")
        await self._seen(204, self.telegram_bot_id, "2026-10-13 12:00:00")
        await self._seen(205, self.telegram_bot_id, "2026-10-01 00:00:00")
        await self.storage.users.set_ban("bot_a", 205, True, "stale")
        text = await self._stats()
        self.assertIn("Активные за 7 дней: <b>2</b>", text)
        self.assertNotIn("updated_at", text)

    async def test_dashboard_counts_user_with_full_and_shadow_once_in_total(self) -> None:
        await self.storage.users.upsert_user("bot_a", 301)
        await self.storage.users.set_ban("bot_a", 301, True, "both")
        await self.storage.users.set_shadow_ban("bot_a", 301, True)
        await self.storage.users.upsert_user("bot_a", 302)
        await self.storage.users.set_ban("bot_a", 302, True, "full")
        await self.storage.users.upsert_user("bot_a", 303)
        await self.storage.users.set_shadow_ban("bot_a", 303, True)
        await self.storage.users.upsert_user("bot_a", 304)
        text = await self._stats()
        self.assertIn("Пользователи: <b>6</b>", text)
        self.assertIn("Баны: <b>3</b> (из них Shadow: <b>2</b>)", text)

    async def test_dashboard_stars_exclude_non_xtr_and_refunded(self) -> None:
        await self._pay(15, "xtr-today", 10, _TODAY_START)
        await self._pay(15, "xtr-yesterday", 20, "2026-10-12 18:59:59")
        await self._pay(15, "rub-today", 100, _TODAY_START, provider="yookassa", currency="RUB")
        await self._pay(15, "usdt-today", 50, _TODAY_START, provider="cryptobot", currency="USDT")
        await self._pay(15, "xtr-refunded", 7, _TODAY_START)
        await self.storage.transactions.mark_refunded("bot_a", "xtr-refunded")
        await self._pay(15, "xtr-other-bot", 99, _TODAY_START, bot_id="bot_b")
        text = await self._stats()
        self.assertIn("Платежи Stars: сегодня <b>10 ⭐</b> · всего <b>30 ⭐</b>", text)
        self.assertNotIn("XTR", text)

    async def test_dashboard_formats_backup_and_maintenance_exactly(self) -> None:
        text = await self._stats(1)
        self.assertIn("Последний бэкап: нет", text)
        self.assertIn("Рубильник: 🟢 снят", text)
        self.assertNotIn("опущен", text)

        def _job(conn) -> None:
            conn.execute(
                """
                INSERT INTO scheduled_job_runs (
                    bot_id, job_key, scheduled_for, completed_at, status, details
                ) VALUES ('bot_a', ?, '2026-10-12 23:00:00', '2026-10-12 23:15:00', 'done', 'nightly.zip')
                """,
                (BACKUP_JOB_KEY,),
            )

        await self.storage.engine.run(_job)
        await self.storage.bot_settings.set_maintenance_status(
            "bot_a", True, reason="pause", updated_by=100
        )
        self.session.requests.clear()
        text = await self._stats(2)
        self.assertIn("Последний бэкап: 2026-10-13 04:15 (UTC+5)", text)
        self.assertIn("Рубильник: 🔴 включён", text)
        self.assertNotIn("nightly.zip", text)
        self.assertNotIn("опущен", text)

    async def test_dashboard_exact_html_and_one_back_button(self) -> None:
        await self.storage.users.upsert_user("bot_a", 401)

        def _today(conn) -> None:
            conn.execute(
                "UPDATE users SET created_at = ? WHERE bot_id = 'bot_a' AND user_id = 401",
                (_TODAY_START,),
            )

        await self.storage.engine.run(_today)
        await self._seen(401, self.telegram_bot_id, _SEEN_EDGE)
        await self.storage.users.upsert_user("bot_a", 402)

        def _keep_old(conn) -> None:
            conn.execute(
                "UPDATE users SET created_at = '2020-01-01 00:00:00' WHERE bot_id = 'bot_a' AND user_id = 402"
            )

        await self.storage.engine.run(_keep_old)
        await self.storage.users.set_ban("bot_a", 402, True, "full")
        await self.storage.users.set_shadow_ban("bot_a", 402, True)
        await self._seen(402, 999, "2026-10-13 12:00:00")
        await self.storage.subscriptions.grant_gift_access("bot_a", 401, granted_by=100)

        def _expired(conn) -> None:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    bot_id, user_id, plan_code, is_lifetime, expires_at,
                    granted_by, status
                ) VALUES ('bot_a', 402, 'old', 0, '2020-01-01 00:00:00', 100, 'active')
                """
            )

        await self.storage.engine.run(_expired)
        with patch("bot_chassis.admin.router.datetime", _FrozenDateTime):
            await self._callback(14, CB_GO_STATS, 1)
        screen = self._named("EditMessageText")[-1]
        self.assertEqual(
            screen.text,
            "📊 <b>Статистика</b>\n"
            "\n"
            "Пользователи: <b>4</b>\n"
            "Новые сегодня: <b>1</b>\n"
            "Активные за 7 дней: <b>1</b>\n"
            "Баны: <b>1</b> (из них Shadow: <b>1</b>)\n"
            "\n"
            "Платежи Stars: сегодня <b>0 ⭐</b> · всего <b>0 ⭐</b>\n"
            "Gift-подписки: <b>1</b>\n"
            "Открытые обращения: <b>0</b>\n"
            "\n"
            "Последний бэкап: нет\n"
            "Рубильник: 🟢 снят",
        )
        self.assertFalse(screen.text.endswith("\n"))
        self.assertEqual(_rows(screen.reply_markup), [("« Назад", CB_HOME)])


_MINIMAL_DOSSIER = """<b>Досье пользователя</b>

Имя: <b>Александр</b> @alexander (ID: <code>123456789</code>)

Статус: 🟢 Активен

Первый визит: 2026-10-05 14:20 UTC
Последняя активность: 2026-10-10 12:45 UTC"""

_FULL_DOSSIER = """<b>Досье пользователя</b>

Имя: <b>Planferno</b> @Planferno (ID: <code>554750808</code>)

Статус: 🔴 Заблокирован · 👤🕶 Теневой бан
Роль: Суперадминистратор

Первый визит: 2026-10-08 02:59 UTC
Последняя активность: 2026-10-10 15:10 UTC

Подписка: Gift (до 2026-11-08)
Токены: 5 шт.
Рефералы: пригласил 3 чел."""

_STOPPED_DOSSIER = """<b>Досье пользователя</b>

Имя: <b>Иван</b> @ivan_user (ID: <code>987654321</code>)

Статус: 🛑 Бот остановлен пользователем

Первый визит: 2026-09-20 10:00 UTC
Последняя активность: 2026-10-01 18:30 UTC"""


class TestAdminV2A1(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=os.path.join(self._tmp.name, "admin.db"),
            superadmin_ids=(100,),
            audit_chat_id=-100,
        )
        self.storage = await create_storage(self.config)
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _user(self, user_id: int, *, username=None, first_name=None, last_name=None, created_at: str) -> None:
        await self.storage.users.upsert_user(
            "bot_a",
            user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

        def _op(conn) -> None:
            conn.execute(
                "UPDATE users SET created_at = ? WHERE bot_id = ? AND user_id = ?",
                (created_at, "bot_a", user_id),
            )

        await self.storage.engine.run(_op)

    async def _seen(self, user_id: int, telegram_bot_id: int, status: str, seen_at: str) -> None:
        def _op(conn) -> None:
            conn.execute(
                """
                INSERT INTO user_bot_statuses (
                    bot_id, user_id, origin_bot_id, telegram_bot_id, status,
                    first_seen_at, last_seen_at, status_changed_at
                ) VALUES (?, ?, 'bot_a', ?, ?, ?, ?, ?)
                """,
                ("bot_a", user_id, telegram_bot_id, status, seen_at, seen_at, seen_at),
            )

        await self.storage.engine.run(_op)

    async def _flags(self, user_id: int, *, banned: bool = False, shadow: bool = False) -> None:
        def _op(conn) -> None:
            conn.execute(
                """
                UPDATE users SET is_banned = ?, is_shadow_banned = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (1 if banned else 0, 1 if shadow else 0, "bot_a", user_id),
            )

        await self.storage.engine.run(_op)

    async def _card(self, user_id: int, telegram_bot_id: int = 123456, *, is_root: bool = False):
        return await _dossier(
            self.storage,
            "bot_a",
            user_id,
            telegram_bot_id=telegram_bot_id,
            is_root=is_root,
        )

    async def test_dossier_exact_minimal_html(self) -> None:
        await self._user(
            123456789,
            username="alexander",
            first_name="Александр",
            created_at="2026-10-05 14:20:45",
        )
        await self.storage.users.set_language_code("bot_a", 123456789, "en")
        await self.storage.users.set_traffic_source("bot_a", 123456789, "ads")
        await self._seen(123456789, 123456, "active", "2026-10-10 12:45:01")
        text, markup = await self._card(123456789)
        self.assertEqual(text, _MINIMAL_DOSSIER)
        self.assertFalse(text.endswith("\n"))
        self.assertNotIn("Язык", text)
        self.assertNotIn("Источник", text)
        self.assertNotIn("Роль:", text)
        self.assertNotIn("Подписка:", text)
        self.assertNotIn("Токены:", text)
        self.assertNotIn("Рефералы:", text)
        self.assertEqual(
            _rows(markup),
            [
                ("🔴 Санкции (Бан)", "adm_usr:menu:sanctions:123456789"),
                ("« Назад", "adm_back"),
                ("В главное меню", "adm_home"),
            ],
        )

    async def test_dossier_exact_full_html(self) -> None:
        user_id = 554750808
        await self._user(user_id, username="Planferno", first_name="Planferno", created_at="2026-10-08 02:59:59")
        await self.storage.roles.grant_role("bot_a", user_id, "admin", granted_by=100)
        await self.storage.roles.grant_role("bot_a", user_id, "superadmin", granted_by=100)
        await self._flags(user_id, banned=True, shadow=True)
        await self._seen(user_id, 123456, "stopped", "2026-10-10 15:10:33")

        def _gift(conn) -> None:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    bot_id, user_id, plan_code, is_lifetime, expires_at, granted_by, status
                ) VALUES ('bot_a', ?, 'default', 0, '2026-11-08 23:30:00', 100, 'active')
                """,
                (user_id,),
            )

        await self.storage.engine.run(_gift)
        for index in range(5):
            charge = f"chg-full-{index}"
            await self.storage.transactions.record_successful_payment(
                bot_id="bot_a",
                user_id=user_id,
                sku_code="vip",
                amount=1,
                telegram_payment_charge_id=charge,
                payment_id=charge,
            )
        for referee in (801, 802, 803):
            ok, err = await self.storage.referrals.record_referral("bot_a", user_id, referee)
            self.assertTrue(ok, err)
        text, markup = await self._card(user_id, is_root=True)
        self.assertEqual(text, _FULL_DOSSIER)
        self.assertNotIn("Администратор\n", text)
        self.assertNotIn("adm_usr:role_adm:", "".join(item[1] for item in _rows(markup)))
        self.assertIn(("🎁 +30 дней VIP", "adm_usr:gift30:554750808"), _rows(markup))
        self.assertIn(("🎟 +1 талон", "adm_usr:addvouch:554750808"), _rows(markup))

    async def test_dossier_formats_utc_without_seconds_or_local_shift(self) -> None:
        await self._user(610, username="u<i>", first_name="A<b>", created_at="2026-10-05 21:30:45")
        await self._seen(610, 123456, "active", "2026-10-05T21:30:45")
        text, _markup = await self._card(610)
        self.assertIn("Первый визит: 2026-10-05 21:30 UTC", text)
        self.assertIn("Последняя активность: 2026-10-05 21:30 UTC", text)
        self.assertNotIn("2026-10-06", text)
        self.assertNotIn("21:30:45", text)
        self.assertIn("Имя: <b>A&lt;b&gt;</b> @u&lt;i&gt; (ID: <code>610</code>)", text)
        self.assertNotIn("A<b>", text)
        self.assertEqual(text.count("&lt;b&gt;"), 1)

        await self._user(611, username="only_name", created_at="2026-10-01 00:00:00")
        username_only, _markup = await self._card(611)
        self.assertIn("Username: @only_name (ID: <code>611</code>)", username_only)
        self.assertNotIn("Последняя активность", username_only)
        self.assertNotIn("Имя:", username_only)

        await self._user(612, created_at="legacy <b> UTC")
        with patch("bot_chassis.admin.router.logger.warning") as warned:
            raw, _markup = await self._card(612)
        self.assertIn("Первый визит: legacy &lt;b&gt; UTC", raw)
        self.assertNotIn("UTC UTC", raw)
        self.assertNotIn("legacy <b>", raw)
        warned.assert_called_once()

        await self._user(613, created_at="2026-10-02 08:00:00")
        bare, _markup = await self._card(613)
        self.assertIn("ID: <code>613</code>", bare)
        self.assertNotIn("Имя:", bare)
        self.assertNotIn("Username:", bare)

    async def test_dossier_status_precedence(self) -> None:
        await self._user(501, first_name="Both", created_at="2026-10-01 00:00:00")
        await self._flags(501, banned=True, shadow=True)
        await self._seen(501, 123456, "deleted", "2026-10-02 00:00:00")
        both, _markup = await self._card(501)
        self.assertIn("Статус: 🔴 Заблокирован · 👤🕶 Теневой бан", both)
        self.assertNotIn("Аккаунт удалён", both)

        await self._user(502, first_name="Ban", created_at="2026-10-01 00:00:00")
        await self._flags(502, banned=True)
        await self._seen(502, 123456, "stopped", "2026-10-02 00:00:00")
        banned, _markup = await self._card(502)
        self.assertIn("Статус: 🔴 Заблокирован", banned)
        self.assertNotIn("Теневой бан", banned)
        self.assertNotIn("остановлен", banned)

        await self._user(503, first_name="Shade", created_at="2026-10-01 00:00:00")
        await self._flags(503, shadow=True)
        await self._seen(503, 123456, "deleted", "2026-10-02 00:00:00")
        shadow, _markup = await self._card(503)
        self.assertIn("Статус: 👤🕶 Теневой бан", shadow)
        self.assertNotIn("Заблокирован", shadow)
        self.assertNotIn("Аккаунт удалён", shadow)

        await self._user(504, first_name="Gone", created_at="2026-10-01 00:00:00")
        await self._seen(504, 123456, "deleted", "2026-10-02 00:00:00")
        deleted, _markup = await self._card(504)
        self.assertIn("Статус: ⚠️ Аккаунт удалён в Telegram", deleted)

        await self._user(505, first_name="Stop", created_at="2026-10-01 00:00:00")
        await self._seen(505, 123456, "stopped", "2026-10-02 00:00:00")
        stopped, _markup = await self._card(505)
        self.assertIn("Статус: 🛑 Бот остановлен пользователем", stopped)

        await self._user(506, first_name="Live", created_at="2026-10-01 00:00:00")
        live, _markup = await self._card(506)
        self.assertIn("Статус: 🟢 Активен", live)
        self.assertNotIn("Последняя активность", live)

    async def test_dossier_uses_current_telegram_bot_lifecycle(self) -> None:
        await self._user(987654321, username="ivan_user", first_name="Иван", created_at="2026-09-20 10:00:59")
        await self._seen(987654321, 123456, "stopped", "2026-10-01 18:30:01")
        await self._seen(987654321, 999, "deleted", "2026-10-11 09:00:00")
        current, _markup = await self._card(987654321, 123456)
        neighbor, _markup = await self._card(987654321, 999)
        self.assertEqual(current, _STOPPED_DOSSIER)
        self.assertIn("Статус: ⚠️ Аккаунт удалён в Telegram", neighbor)
        self.assertNotIn("остановлен", neighbor)
        self.assertIn("Последняя активность: 2026-10-11 09:00 UTC", neighbor)
        self.assertNotIn("BPD", current)
        self.assertNotIn("Санкции сети", current)

    async def test_dossier_action_stays_in_place(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="neo", first_name="Neo")
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        dispatcher = Dispatcher()

        def extra_rows(user_id: int):
            return [[("Grant hours", f"adm_ops:grant_hours:{user_id}")]]

        async def extra_lines(user_id: int):
            return [f"Extra hours: {user_id}"]

        dispatcher.include_router(
            create_admin_router(
                "bot_a",
                self.storage,
                self.config,
                extra_user_dossier_lines=extra_lines,
                extra_user_dossier_rows=extra_rows,
            )
        )
        panel = Message(
            message_id=50,
            date=1,
            chat=Chat(id=100, type="private"),
            from_user=_user(100),
            text="dossier",
        )

        async def click(data: str, update_id: int) -> None:
            await dispatcher.feed_update(
                bot,
                Update(
                    update_id=update_id,
                    callback_query=CallbackQuery(
                        id=str(update_id),
                        from_user=_user(100),
                        chat_instance="x",
                        data=data,
                        message=panel,
                    ),
                ),
            )

        await click("adm_usr:sanction:ban:16", 1)
        await click("adm_usr:menu:dossier:16", 2)
        edits = [item for item in session.requests if item.__class__.__name__ == "EditMessageText"]
        self.assertEqual(len(edits), 2)
        self.assertIn("Статус: 🔴 Заблокирован", edits[0].text)
        self.assertIn("Статус: 🔴 Заблокирован", edits[1].text)
        self.assertTrue(edits[0].text.endswith("Extra hours: 16"))
        self.assertEqual(_rows(edits[0].reply_markup)[0], ("🟢 Снять бан", "adm_usr:sanction:unban:16"))
        self.assertEqual(_rows(edits[1].reply_markup)[-3], ("Grant hours", "adm_ops:grant_hours:16"))
        self.assertTrue((await self.storage.users.get_user("bot_a", 16)).is_banned)
        homes = [
            item
            for item in session.requests
            if item.__class__.__name__ == "SendMessage" and item.chat_id == 100 and "Админка" in (item.text or "")
        ]
        self.assertFalse(homes)

        session.requests.clear()
        await click("adm_usr:role_adm:16", 3)
        self.assertFalse(await self.storage.roles.has_any_role("bot_a", 16, ("admin",)))
        self.assertFalse([item for item in session.requests if item.__class__.__name__ == "EditMessageText"])
        await bot.session.close()


class TestAdminV2A2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=os.path.join(self._tmp.name, "admin.db"),
            superadmin_ids=(100,),
            audit_chat_id=-100,
        )
        self.storage = await create_storage(self.config)
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.dp = Dispatcher()
        self.dp.include_router(create_admin_router("bot_a", self.storage, self.config))

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def _click(self, user_id: int, data: str, update_id: int) -> None:
        panel = Message(
            message_id=50,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=_user(user_id),
            text="dossier",
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

    def _edits(self):
        return [item for item in self.session.requests if item.__class__.__name__ == "EditMessageText"]

    async def _flags(self, user_id: int, *, banned: bool = False, shadow: bool = False) -> None:
        await self.storage.users.upsert_user("bot_a", user_id, username=f"u{user_id}")

        def _op(conn) -> None:
            conn.execute(
                """
                UPDATE users SET is_banned = ?, is_shadow_banned = ?
                WHERE bot_id = ? AND user_id = ?
                """,
                (1 if banned else 0, 1 if shadow else 0, "bot_a", user_id),
            )

        await self.storage.engine.run(_op)

    def test_sanction_parser_rejects_wrong_shape_and_action(self) -> None:
        self.assertEqual(_parse_sanction_callback("adm_usr:sanction:ban:16"), ("ban", 16))
        self.assertEqual(_parse_sanction_callback("adm_usr:sanction:unban:16"), ("unban", 16))
        self.assertEqual(_parse_sanction_callback("adm_usr:sanction:shadow_on:16"), ("shadow_on", 16))
        self.assertEqual(_parse_sanction_callback("adm_usr:sanction:shadow_off:16"), ("shadow_off", 16))
        for raw in (
            "adm_usr:sanction:ban",
            "adm_usr:sanction:ban:16:1",
            "adm_usr:sanction:toggle:16",
            "adm_usr:sanction:no_reason:16",
            "adm_usr:sanction:cancel:16",
            "adm_usr:ban:16",
            "adm_usr:shban:16",
            "adm_usr:sanction:ban:abc",
            "adm_usr:sanction:BAN:16",
            "",
        ):
            self.assertIsNone(_parse_sanction_callback(raw), raw)

    async def test_sanction_menu_has_exact_labels_for_each_flag_combination(self) -> None:
        cases = (
            (21, False, False, "🔴 Выдать бан", "ban", "👤🕶 Включить теневой бан", "shadow_on"),
            (22, True, False, "🟢 Снять бан", "unban", "👤🕶 Включить теневой бан", "shadow_on"),
            (23, False, True, "🔴 Выдать бан", "ban", "👤🕶 Снять теневой бан", "shadow_off"),
            (24, True, True, "🟢 Снять бан", "unban", "👤🕶 Снять теневой бан", "shadow_off"),
        )
        for user_id, banned, shadow, ban_label, ban_action, shadow_label, shadow_action in cases:
            await self._flags(user_id, banned=banned, shadow=shadow)
            profile = await self.storage.users.get_user("bot_a", user_id)
            rows = _rows(_sanctions_keyboard(profile))
            self.assertEqual(
                rows,
                [
                    (ban_label, f"adm_usr:sanction:{ban_action}:{user_id}"),
                    (shadow_label, f"adm_usr:sanction:{shadow_action}:{user_id}"),
                    ("« Назад в досье", f"adm_usr:menu:dossier:{user_id}"),
                    ("В главное меню", CB_HOME),
                ],
            )
            joined = " ".join(label for label, _data in rows)
            self.assertNotIn("Забанить", joined)
            self.assertNotIn("Разбанить", joined)
            self.assertNotIn("Shadow", joined)

    async def test_sanction_menu_uses_fresh_flags(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="neo")
        await self._click(14, "adm_usr:menu:sanctions:16", 1)
        self.assertEqual(_rows(self._edits()[0].reply_markup)[0], ("🔴 Выдать бан", "adm_usr:sanction:ban:16"))
        await self._flags(16, banned=True)
        self.session.requests.clear()
        await self._click(14, "adm_usr:menu:sanctions:16", 2)
        self.assertEqual(_rows(self._edits()[0].reply_markup)[0], ("🟢 Снять бан", "adm_usr:sanction:unban:16"))
        self.assertIn("Статус: 🔴 Заблокирован", self._edits()[0].text)

    async def test_unban_and_shadow_off_are_explicit_idempotent_sets(self) -> None:
        await self._flags(16, banned=True, shadow=True)
        await self._click(14, "adm_usr:sanction:unban:16", 1)
        await self._click(14, "adm_usr:sanction:unban:16", 2)
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_banned)
        self.assertTrue((await self.storage.users.get_user("bot_a", 16)).is_shadow_banned)
        edits = self._edits()
        self.assertEqual(len(edits), 2)
        self.assertEqual(_rows(edits[0].reply_markup)[0], ("🔴 Выдать бан", "adm_usr:sanction:ban:16"))
        self.assertEqual(_rows(edits[1].reply_markup)[0], ("🔴 Выдать бан", "adm_usr:sanction:ban:16"))
        self.assertIn("Статус: 👤🕶 Теневой бан", edits[1].text)
        homes = [
            item
            for item in self.session.requests
            if item.__class__.__name__ == "SendMessage" and item.chat_id == 14 and "Админка" in (item.text or "")
        ]
        self.assertFalse(homes)

        self.session.requests.clear()
        await self._click(14, "adm_usr:sanction:shadow_off:16", 3)
        await self._click(14, "adm_usr:sanction:shadow_off:16", 4)
        profile = await self.storage.users.get_user("bot_a", 16)
        self.assertFalse(profile.is_banned)
        self.assertFalse(profile.is_shadow_banned)
        later = self._edits()
        self.assertEqual(_rows(later[-1].reply_markup)[1], ("👤🕶 Включить теневой бан", "adm_usr:sanction:shadow_on:16"))
        self.assertIn("Статус: 🟢 Активен", later[-1].text)

    async def test_sanction_error_does_not_render_success(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="neo")
        await self._click(14, "adm_usr:sanction:ban:100", 1)
        self.assertFalse((await self.storage.users.get_user("bot_a", 100)).is_banned)
        answers = [item for item in self.session.requests if item.__class__.__name__ == "AnswerCallbackQuery"]
        self.assertEqual(answers[-1].text, "Нельзя забанить последнего суперадмина")
        self.assertTrue(answers[-1].show_alert)
        self.assertFalse(self._edits())

        self.session.requests.clear()
        await self._click(100, "adm_usr:sanction:shadow_on:14", 2)
        self.assertFalse((await self.storage.users.get_user("bot_a", 14)).is_shadow_banned)
        answers = [item for item in self.session.requests if item.__class__.__name__ == "AnswerCallbackQuery"]
        self.assertEqual(answers[-1].text, "Нельзя наложить тень на admin или superadmin")
        self.assertTrue(answers[-1].show_alert)
        self.assertFalse(self._edits())

        self.session.requests.clear()
        await self._click(14, "adm_usr:sanction:no_reason:16", 3)
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_banned)
        self.assertFalse(self._edits())


if __name__ == "__main__":
    unittest.main()
