"""Админка: фильтры, аудит и экран /admin. Команды и рассылка сюда не входят."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import csv
import io
import os
import sqlite3
import tempfile
from pathlib import Path
import time
import unittest
import zipfile
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, FSInputFile, Message, Update, User

from bot_chassis.admin.audit import send_admin_audit
from bot_chassis.admin.broadcast import (
    BROADCAST_INTERVAL,
    CB_BROADCAST_CANCEL,
    CB_BROADCAST_GO,
    CB_BROADCAST_STOP,
    reset_broadcast_sessions,
)
from bot_chassis.admin.filters import AdminRoleFilter, SuperadminRoleFilter, _user_id
from bot_chassis.admin.router import (
    ALREADY_GRANTED,
    BAN_USAGE,
    BACKUP_LIMIT_BYTES,
    BACKUP_TOO_LARGE,
    BACKUP_USAGE,
    CB_BROADCAST,
    CB_EXPORT,
    CB_MAINT,
    EXPORT_USAGE,
    GIFT_NOT_FOUND,
    GIFT_REVOKE_USAGE,
    GIFT_USAGE,
    GRANT_USAGE,
    INVALID_ROLE,
    LAST_SUPERADMIN,
    LAST_SUPERADMIN_ROLE,
    MAINTENANCE_USAGE,
    REVOKE_USAGE,
    REFUND_ALREADY,
    REFUND_NOT_FOUND,
    REFUND_NOT_STARS,
    REFUND_USAGE,
    ROLE_NOT_FOUND,
    SHADOW_USAGE,
    SUPERADMIN_ONLY,
    TARGET_IS_ADMIN,
    USER_NOT_FOUND,
    USER_USAGE,
    create_admin_router,
)
from bot_chassis.config import BotChassisConfig
from bot_chassis.followup import PendingInputKind
from bot_chassis.storage import create_storage


def _message(user: User | None) -> Message:
    return Message(
        message_id=1,
        date=1,
        chat=Chat(id=1, type="private"),
        from_user=user,
        text="/admin",
    )


def _callback(user: User) -> CallbackQuery:
    return CallbackQuery(id="cb", from_user=user, chat_instance="x", data="adm_usr:ban:1")


class TestAdminRoleFilters(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.storage = await create_storage(
            BotChassisConfig(bot_id="bot_a", db_path=self.db_path, superadmin_ids=(100,))
        )
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        await create_storage(
            BotChassisConfig(bot_id="bot_b", db_path=self.db_path, superadmin_ids=(200,))
        )
        self.admin = AdminRoleFilter("bot_a", self.storage.roles)
        self.root = SuperadminRoleFilter("bot_a", self.storage.roles)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_role_filters_split_admin_and_superadmin(self) -> None:
        self.assertFalse(await self.admin(_message(None)))
        self.assertFalse(await self.root(_message(None)))

        stranger = _user(5)
        self.assertFalse(await self.admin(_message(stranger)))
        self.assertFalse(await self.root(_callback(stranger)))

        admin = _user(14)
        self.assertTrue(await self.admin(_message(admin)))
        self.assertTrue(await self.admin(_callback(admin)))
        self.assertFalse(await self.root(_message(admin)))
        self.assertFalse(await self.root(_callback(admin)))

        root = _user(100)
        self.assertTrue(await self.admin(_message(root)))
        self.assertTrue(await self.root(_callback(root)))

        other_bot = _user(200)
        self.assertFalse(await self.admin(_message(other_bot)))
        self.assertFalse(await self.root(_message(other_bot)))

    async def test_user_id_reads_wrapped_update(self) -> None:
        wrapped = Update(update_id=1, message=_message(_user(42)))
        self.assertEqual(_user_id(wrapped), 42)


class TestAdminAudit(unittest.IsolatedAsyncioTestCase):
    async def test_skips_send_when_audit_chat_missing(self) -> None:
        bot = AsyncMock()
        config = BotChassisConfig(bot_id="bot_a", audit_chat_id=None)
        await send_admin_audit(bot, config, "Бан @ann: <reason>")
        bot.send_message.assert_not_awaited()

    async def test_escapes_text_and_swallows_send_errors(self) -> None:
        bot = AsyncMock()
        config = BotChassisConfig(bot_id="bot_a", audit_chat_id=-100)
        await send_admin_audit(bot, config, "Бан @ann: <script>")
        bot.send_message.assert_awaited_once()
        chat_id, text = bot.send_message.await_args.args
        self.assertEqual(chat_id, -100)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)
        self.assertEqual(bot.send_message.await_args.kwargs["parse_mode"], "HTML")

        bot.send_message.side_effect = RuntimeError("telegram down")
        with patch("bot_chassis.admin.audit.logger") as log:
            await send_admin_audit(bot, config, "ещё раз")
        log.exception.assert_called_once()

    async def test_html_audit_falls_back_when_parser_rejects_markup(self) -> None:
        bot = AsyncMock()
        config = BotChassisConfig(bot_id="bot_a", audit_chat_id=-100)
        await send_admin_audit(bot, config, "<b>ok</b>", is_html=True)
        self.assertEqual(bot.send_message.await_args.args[1], "<b>ok</b>")

        method = bot.send_message.await_args
        bot.send_message.reset_mock()

        async def reject_raw(chat_id, text, parse_mode=None):
            if "<b>" in text:
                raise TelegramBadRequest(method=method, message="can't parse entities")
            return True

        bot.send_message.side_effect = reject_raw
        await send_admin_audit(bot, config, "<b>ok</b>", is_html=True)
        self.assertEqual(bot.send_message.await_args_list[-1].args[1], "&lt;b&gt;ok&lt;/b&gt;")


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name == "SendDocument":
            doc = getattr(method, "document", None)
            if isinstance(doc, FSInputFile):
                method._test_payload = Path(doc.path).read_bytes()
        if name in ("SendMessage", "EditMessageText"):
            return Message(
                message_id=getattr(method, "message_id", 50) or 50,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


class TestAdminHome(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
            audit_chat_id=-100,
        )
        self.storage = await create_storage(self.config)
        reset_broadcast_sessions()
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        await self.storage.users.upsert_user("bot_a", 15)
        await self.storage.users.set_ban("bot_a", 15, True, "spam")
        await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=15,
            sku_code="audit",
            amount=50,
            telegram_payment_charge_id="chg-home",
        )
        await self.storage.subscriptions.grant_gift_access("bot_a", 15, granted_by=100, days=30)
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.dp = Dispatcher()
        self.dp.include_router(create_admin_router("bot_a", self.storage, self.config))

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        self._tmp.cleanup()

    async def test_admin_home_hidden_from_stranger_and_banned(self) -> None:
        await self._feed_command(5, 1)
        await self.storage.users.set_ban("bot_a", 14, True, "blocked")
        await self._feed_command(14, 2)
        self.assertFalse(self._named("SendMessage"))
        on, _reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertFalse(on)

    async def test_admin_home_summary_and_maintenance_toggle(self) -> None:
        await self._feed_command(14, 1)
        sent = self._named("SendMessage")
        self.assertEqual(len(sent), 1)
        text = sent[0].text
        self.assertIn("Пользователи: 3", text)
        self.assertIn("Бан: 1", text)
        self.assertIn("Оплаты: 50 XTR", text)
        self.assertIn("Подарки: 1", text)
        self.assertIn("🟢 снят", text)
        callbacks = [button.callback_data for row in sent[0].reply_markup.inline_keyboard for button in row]
        self.assertEqual(callbacks, [CB_MAINT, CB_EXPORT, CB_BROADCAST])

        self.session.requests.clear()
        panel = Message(
            message_id=50,
            date=1,
            chat=Chat(id=14, type="private"),
            from_user=_user(14, username="a<b>"),
            text="admin",
        )
        await self._feed_callback(14, CB_MAINT, 2, panel, username="a<b>")
        on, _reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertTrue(on)
        edited = self._named("EditMessageText")
        self.assertEqual(len(edited), 1)
        self.assertIn("🔴 опущен", edited[0].text)
        audit = [item for item in self._named("SendMessage") if item.chat_id == -100]
        self.assertEqual(len(audit), 1)
        self.assertIn("Рубильник опущен", audit[0].text)
        self.assertIn("&lt;b&gt;", audit[0].text)
        self.assertNotIn("<b>", audit[0].text)
        self.assertEqual(audit[0].parse_mode, "HTML")

    async def test_export_button_is_superadmin_only(self) -> None:
        panel = Message(message_id=50, date=1, chat=Chat(id=14, type="private"), text="admin")
        await self._feed_callback(14, CB_EXPORT, 1, panel)
        answers = self._named("AnswerCallbackQuery")
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0].text, SUPERADMIN_ONLY)
        self.assertTrue(answers[0].show_alert)
        self.assertFalse(self._named("SendDocument"))

        self.session.requests.clear()
        await self._feed_callback(100, CB_EXPORT, 2, panel)
        root_answer = self._named("AnswerCallbackQuery")
        self.assertEqual(len(root_answer), 1)
        self.assertNotEqual(root_answer[0].text, SUPERADMIN_ONLY)
        documents = self._named("SendDocument")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].chat_id, 100)
        self.assertEqual(documents[0].document.filename, "export.zip")
        self.assertTrue(any("Экспорт all" in item.text for item in self._named("SendMessage") if item.chat_id == -100))
        self.assertFalse(any(item.chat_id == -100 for item in documents))

        self.session.requests.clear()
        await self._feed_callback(14, CB_BROADCAST, 3, panel)
        self.assertEqual(len(self._named("AnswerCallbackQuery")), 1)
        self.assertTrue(any(item.text == "Пришлите текст рассылки." for item in self._named("SendMessage") if item.chat_id == 14))

    async def test_ban_unban_and_shadowban(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="neo")
        await self._feed_text(14, "/ban@ChassisBot 16 <script>", 1)
        banned = await self.storage.users.get_user("bot_a", 16)
        self.assertTrue(banned.is_banned)
        self.assertEqual(banned.ban_reason, "<script>")
        actor_chat = [item for item in self._named("SendMessage") if item.chat_id == 14]
        self.assertTrue(any("забанен" in item.text for item in actor_chat))
        audit = [item for item in self._named("SendMessage") if item.chat_id == -100]
        self.assertTrue(any("Бан user_id=16" in item.text and "&lt;script&gt;" in item.text for item in audit))
        self.assertTrue(all("<script>" not in item.text for item in audit))

        self.session.requests.clear()
        await self._feed_text(14, "/unban 16", 2)
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_banned)
        self.assertTrue(any("Разбан user_id=16" in item.text for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(14, "/shadowban 16 1", 3)
        self.assertTrue((await self.storage.users.get_user("bot_a", 16)).is_shadow_banned)
        await self._feed_text(14, "/shadowban 16 0", 4)
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_shadow_banned)
        self.session.requests.clear()
        await self._feed_text(14, "/shadowban 14 0", 5)
        self.assertFalse((await self.storage.users.get_user("bot_a", 14)).is_shadow_banned)
        self.assertTrue(any("снят" in item.text for item in self._named("SendMessage") if item.chat_id == -100))

    async def test_moderation_rejects_protected_and_unknown_targets(self) -> None:
        await self._feed_text(5, "/ban 16 spam", 1)
        await self._feed_text(14, "/ban", 2)
        await self._feed_text(14, "/ban 100", 3)
        await self._feed_text(14, "/shadowban 14 1", 4)
        await self._feed_text(14, "/shadowban 999 1", 5)
        await self._feed_text(14, "/shadowban 16", 6)
        self.assertFalse((await self.storage.users.get_user("bot_a", 100)).is_banned)
        self.assertFalse((await self.storage.users.get_user("bot_a", 14)).is_shadow_banned)
        self.assertIsNone(await self.storage.users.get_user("bot_a", 999))
        texts = [item.text for item in self._named("SendMessage") if item.chat_id == 14]
        self.assertIn(BAN_USAGE, texts)
        self.assertIn(LAST_SUPERADMIN, texts)
        self.assertIn(TARGET_IS_ADMIN, texts)
        self.assertIn(USER_NOT_FOUND, texts)
        self.assertIn(SHADOW_USAGE, texts)
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self.storage.users.set_ban("bot_a", 14, True, "blocked")
        await self.storage.users.upsert_user("bot_a", 16)
        await self._feed_text(14, "/ban 16 spam", 7)
        self.assertFalse(self._named("SendMessage"))
        self.assertFalse((await self.storage.users.get_user("bot_a", 16)).is_banned)

    async def test_grant_and_revoke_roles(self) -> None:
        await self._feed_text(14, "/grant 16 admin", 1)
        await self._feed_text(5, "/grant 16 admin", 2)
        self.assertIsNone(await self.storage.users.get_user("bot_a", 16))
        self.assertFalse(self._named("SendMessage"))

        self.session.requests.clear()
        await self._feed_text(100, "/grant@ChassisBot 16 admin", 3)
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 16, ("admin",)))
        self.assertTrue(any("выдана" in item.text for item in self._named("SendMessage") if item.chat_id == 100))
        self.assertTrue(
            any("Роль admin выдана user_id=16" in item.text for item in self._named("SendMessage") if item.chat_id == -100)
        )

        self.session.requests.clear()
        await self._feed_text(100, "/grant 16 admin", 4)
        self.assertIn(ALREADY_GRANTED, [item.text for item in self._named("SendMessage") if item.chat_id == 100])
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(100, "/revoke 100 superadmin", 5)
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 100, ("superadmin",)))
        self.assertIn(LAST_SUPERADMIN_ROLE, [item.text for item in self._named("SendMessage") if item.chat_id == 100])

        self.session.requests.clear()
        await self._feed_text(100, "/grant 17 superadmin", 6)
        await self._feed_text(100, "/revoke 17 superadmin", 7)
        self.assertFalse(await self.storage.roles.has_any_role("bot_a", 17, ("superadmin",)))
        self.assertTrue(any("Роль superadmin снята user_id=17" in item.text for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(100, "/revoke 16 admin", 8)
        self.assertFalse(await self.storage.roles.has_any_role("bot_a", 16, ("admin",)))

    async def test_role_commands_reject_bad_args_and_banned_actor(self) -> None:
        await self._feed_text(100, "/grant", 1)
        await self._feed_text(100, "/revoke 16", 2)
        await self._feed_text(100, "/grant 18 moderator", 3)
        await self._feed_text(100, "/revoke 999 admin", 4)
        self.assertIsNone(await self.storage.users.get_user("bot_a", 18))
        texts = [item.text for item in self._named("SendMessage") if item.chat_id == 100]
        self.assertIn(GRANT_USAGE, texts)
        self.assertIn(REVOKE_USAGE, texts)
        self.assertIn(INVALID_ROLE, texts)
        self.assertIn(ROLE_NOT_FOUND, texts)
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self.storage.roles.grant_role("bot_a", 19, "superadmin", granted_by=100)
        await self.storage.users.set_ban("bot_a", 100, True, "blocked")
        await self._feed_text(100, "/grant 20 admin", 5)
        self.assertFalse(self._named("SendMessage"))
        self.assertIsNone(await self.storage.users.get_user("bot_a", 20))

    async def test_gift_replaces_access_and_revoke(self) -> None:
        await self._feed_text(14, "/gift 16", 1)
        await self._feed_text(5, "/gift 16 30", 2)
        self.assertIsNone(await self.storage.users.get_user("bot_a", 16))
        self.assertFalse(self._named("SendMessage"))

        self.session.requests.clear()
        await self._feed_text(100, "/gift@ChassisBot 16", 3)
        lifetime = await self.storage.subscriptions.get_active_subscription("bot_a", 16)
        self.assertIsNotNone(lifetime)
        self.assertTrue(lifetime.is_lifetime)
        self.assertTrue(
            any("Подарок выдан user_id=16 (бессрочно)" in item.text for item in self._named("SendMessage") if item.chat_id == -100)
        )

        self.session.requests.clear()
        await self._feed_text(100, "/gift 16 10", 4)
        replaced = await self.storage.subscriptions.get_active_subscription("bot_a", 16)
        self.assertFalse(replaced.is_lifetime)
        expires = datetime.strptime(replaced.expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        self.assertGreater(expires, now + timedelta(days=8))
        self.assertLess(expires, now + timedelta(days=12))
        self.assertEqual(await self._active_gifts(16), 1)

        self.session.requests.clear()
        await self._feed_text(100, "/gift_revoke 16", 5)
        self.assertFalse(await self.storage.subscriptions.has_active_access("bot_a", 16))
        self.assertTrue(any("Подарок отозван user_id=16" in item.text for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(100, "/gift", 6)
        await self._feed_text(100, "/gift 18 days", 7)
        await self._feed_text(100, "/gift_revoke", 8)
        await self._feed_text(100, "/gift_revoke 16", 9)
        self.assertIsNone(await self.storage.users.get_user("bot_a", 18))
        texts = [item.text for item in self._named("SendMessage") if item.chat_id == 100]
        self.assertIn(GIFT_USAGE, texts)
        self.assertIn(GIFT_REVOKE_USAGE, texts)
        self.assertIn(GIFT_NOT_FOUND, texts)
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self.storage.roles.grant_role("bot_a", 19, "superadmin", granted_by=100)
        await self.storage.users.set_ban("bot_a", 100, True, "blocked")
        await self._feed_text(100, "/gift 20 5", 10)
        self.assertFalse(self._named("SendMessage"))
        self.assertIsNone(await self.storage.users.get_user("bot_a", 20))

    async def test_user_dossier_card_and_actions(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16, username="a<b>", first_name="Ann")
        await self.storage.users.set_traffic_source("bot_a", 16, "ads")
        await self._feed_text(5, "/user 16", 1)
        await self._feed_text(14, "/user", 2)
        await self._feed_text(14, "/user 999", 3)
        self.assertIsNone(await self.storage.users.get_user("bot_a", 999))
        self.assertEqual(
            [item.text for item in self._named("SendMessage") if item.chat_id == 14],
            [USER_USAGE, USER_NOT_FOUND],
        )
        self.assertFalse(any(item.chat_id == 5 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(14, "/user@ChassisBot 16", 4)
        sent = self._named("SendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn("@a&lt;b&gt;", sent[0].text)
        self.assertNotIn("a<b>", sent[0].text)
        self.assertIn("ID: 16", sent[0].text)
        self.assertIn("Имя: Ann", sent[0].text)
        self.assertIn("Источник / Реф: ads", sent[0].text)
        self.assertIn("Активен", sent[0].text)
        self.assertIn("Теневой бан: НЕТ", sent[0].text)
        self.assertIn("Роли: нет", sent[0].text)
        self.assertIn("VIP Доступ: Отсутствует", sent[0].text)
        self.assertIn("Талоны: 0 шт. (Оплат всего: 0)", sent[0].text)
        self.assertIn("Пригласил рефералов: 0", sent[0].text)
        buttons = [button for row in sent[0].reply_markup.inline_keyboard for button in row]
        self.assertEqual(
            [(button.text, button.callback_data) for button in buttons],
            [
                ("🔴 Забанить", "adm_usr:ban:16"),
                ("👻 Теневой бан: ВКЛ", "adm_usr:shban:16"),
                ("🎁 +30 дней VIP", "adm_usr:gift30:16"),
                ("🎟 +1 талон", "adm_usr:addvouch:16"),
                ("👑 Роль Admin", "adm_usr:role_adm:16"),
                ("« Главное меню админки", "adm_home"),
            ],
        )

        panel = Message(message_id=50, date=1, chat=Chat(id=14, type="private"), text="dossier")
        self.session.requests.clear()
        await self._feed_callback(14, "adm_usr:gift30:16", 5, panel)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, SUPERADMIN_ONLY)
        self.assertTrue(self._named("AnswerCallbackQuery")[0].show_alert)
        self.assertIsNone(await self.storage.subscriptions.get_active_subscription("bot_a", 16))

        self.session.requests.clear()
        await self._feed_callback(100, "adm_usr:gift30:16", 6, panel)
        gift = await self.storage.subscriptions.get_active_subscription("bot_a", 16)
        self.assertIsNotNone(gift)
        self.assertFalse(gift.is_lifetime)
        self.assertEqual(await self._active_gifts(16), 1)
        self.assertIn("до ", self._named("EditMessageText")[0].text)
        self.assertTrue(any("30 дн." in item.text for item in self._named("SendMessage") if item.chat_id == -100))

        self.session.requests.clear()
        await self._feed_callback(14, "adm_usr:ban:16", 7, panel)
        self.assertTrue((await self.storage.users.get_user("bot_a", 16)).is_banned)
        self.assertIn("Забанен", self._named("EditMessageText")[0].text)
        self.assertIn("🟢 Разбанить", self._named("EditMessageText")[0].reply_markup.inline_keyboard[0][0].text)

        self.session.requests.clear()
        await self._feed_callback(14, "adm_usr:ban:100", 8, panel)
        self.assertFalse((await self.storage.users.get_user("bot_a", 100)).is_banned)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, LAST_SUPERADMIN)
        self.assertFalse(self._named("EditMessageText"))

        self.session.requests.clear()
        await self._feed_callback(14, "adm_usr:shban:14", 9, panel)
        self.assertFalse((await self.storage.users.get_user("bot_a", 14)).is_shadow_banned)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, TARGET_IS_ADMIN)

        self.session.requests.clear()
        await self._feed_callback(100, "adm_usr:addvouch:16", 10, panel)
        vouchers = await self.storage.transactions.get_active_vouchers("bot_a", 16)
        self.assertEqual(len(vouchers), 1)
        self.assertEqual(vouchers[0].provider, "admin_grant")
        self.assertEqual(vouchers[0].sku_code, "admin_grant")
        self.assertEqual(vouchers[0].amount, 0)
        self.assertTrue(vouchers[0].payment_id.startswith("admin:"))
        self.assertTrue(any("Талон выдан" in item.text for item in self._named("SendMessage") if item.chat_id == -100))
        self.assertIn("Талоны: 1 шт. (Оплат всего: 1)", self._named("EditMessageText")[0].text)

        self.session.requests.clear()
        await self._feed_callback(100, "adm_usr:role_adm:16", 11, panel)
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 16, ("admin",)))
        await self._feed_callback(100, "adm_usr:role_adm:16", 12, panel)
        self.assertFalse(await self.storage.roles.has_any_role("bot_a", 16, ("admin",)))

        self.session.requests.clear()
        await self._feed_callback(100, "adm_usr:role_adm:100", 13, panel)
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 100, ("admin",)))
        await self._feed_callback(100, "adm_usr:role_adm:100", 14, panel)
        self.assertTrue(await self.storage.roles.has_any_role("bot_a", 100, ("admin",)))
        self.assertEqual(self._named("AnswerCallbackQuery")[-1].text, LAST_SUPERADMIN_ROLE)

        self.session.requests.clear()
        await self.storage.users.set_ban("bot_a", 14, True, "blocked")
        await self._feed_text(14, "/user 16", 15)
        self.assertFalse(self._named("SendMessage"))

    async def test_export_scopes_stay_with_the_caller(self) -> None:
        await self.storage.users.upsert_user("bot_b", 777, username="other")
        await self._feed_text(14, "/export", 1)
        await self._feed_text(5, "/export users", 2)
        self.assertFalse(self._named("SendDocument"))
        self.assertFalse(self._named("SendMessage"))

        self.session.requests.clear()
        await self._feed_text(100, "/export@ChassisBot users", 3)
        filename, payload = _document(self._named("SendDocument")[0])
        self.assertEqual(self._named("SendDocument")[0].chat_id, 100)
        self.assertEqual(filename, "users.csv")
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        user_ids = {row[0] for row in _csv_rows(payload)[1:]}
        self.assertIn("15", user_ids)
        self.assertNotIn("777", user_ids)
        self.assertTrue(any("Экспорт users" in item.text for item in self._named("SendMessage") if item.chat_id == -100))

        self.session.requests.clear()
        await self._feed_text(100, "/export payments", 4)
        _name, payments = _document(self._named("SendDocument")[0])
        self.assertIn("chg-home", payments.decode("utf-8-sig"))

        self.session.requests.clear()
        await self._feed_text(100, "/export gifts", 5)
        _name, gifts = _document(self._named("SendDocument")[0])
        gift_users = {row[1] for row in _csv_rows(gifts)[1:]}
        self.assertIn("15", gift_users)

        self.session.requests.clear()
        await self._feed_text(100, "/export", 6)
        filename, payload = _document(self._named("SendDocument")[0])
        self.assertEqual(filename, "export.zip")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(archive.namelist(), ["users.csv", "payments.csv", "gifts.csv"])
            packed = archive.read("users.csv")
            self.assertTrue(packed.startswith(b"\xef\xbb\xbf"))
            packed_ids = {row[0] for row in _csv_rows(packed)[1:]}
            self.assertNotIn("777", packed_ids)

        self.session.requests.clear()
        await self._feed_text(100, "/export secret", 7)
        self.assertFalse(self._named("SendDocument"))
        self.assertIn(EXPORT_USAGE, [item.text for item in self._named("SendMessage") if item.chat_id == 100])
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self.storage.roles.grant_role("bot_a", 19, "superadmin", granted_by=100)
        await self.storage.users.set_ban("bot_a", 100, True, "blocked")
        await self._feed_text(100, "/export all", 8)
        self.assertFalse(self._named("SendDocument"))
        self.assertFalse(self._named("SendMessage"))

    async def test_backup_goes_only_to_the_caller(self) -> None:
        await self.storage.roles.grant_role("bot_a", 19, "superadmin", granted_by=100)
        await self._feed_text(14, "/backup", 1)
        await self._feed_text(5, "/backup", 2)
        await self._feed_text(100, "/backup now", 3)
        self.assertFalse(self._named("SendDocument"))
        self.assertEqual(
            [item.text for item in self._named("SendMessage") if item.chat_id == 100],
            [BACKUP_USAGE],
        )
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(100, "/backup@ChassisBot", 4)
        documents = self._named("SendDocument")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].chat_id, 100)
        self.assertEqual(documents[0].document.filename, "backup.db")
        self.assertNotIn(19, [item.chat_id for item in documents])
        self.assertNotIn(-100, [item.chat_id for item in documents])
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
            handle.write(documents[0]._test_payload)
            copy_path = handle.name
        try:
            conn = sqlite3.connect(copy_path)
            try:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE bot_id = ? AND user_id = ?",
                    ("bot_a", 15),
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(copy_path)
        self.assertIsNotNone(row)

        self.session.requests.clear()
        with patch("bot_chassis.admin.router.os.path.getsize", return_value=BACKUP_LIMIT_BYTES):
            await self._feed_text(100, "/backup", 5)
        self.assertFalse(self._named("SendDocument"))
        self.assertIn(BACKUP_TOO_LARGE, [item.text for item in self._named("SendMessage") if item.chat_id == 100])
        self.assertFalse(any(item.chat_id == -100 for item in self.session.requests))

        self.session.requests.clear()
        await self.storage.users.set_ban("bot_a", 100, True, "blocked")
        await self._feed_text(100, "/backup", 6)
        self.assertFalse(self._named("SendDocument"))
        self.assertFalse(self._named("SendMessage"))

    async def test_refund_calls_telegram_before_marking(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16)
        await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=16,
            sku_code="admin_grant",
            amount=0,
            telegram_payment_charge_id="admin:abc",
            provider="admin_grant",
            payment_id="admin:abc",
        )
        await self._feed_text(5, "/refund 15 chg-home", 1)
        await self._feed_text(14, "/refund", 2)
        await self._feed_text(14, "/refund 14 chg-home", 3)
        await self._feed_text(14, "/refund 16 admin:abc", 4)
        self.assertFalse(self._named("RefundStarPayment"))
        texts = [item.text for item in self._named("SendMessage") if item.chat_id == 14]
        self.assertIn(REFUND_USAGE, texts)
        self.assertIn(REFUND_NOT_FOUND, texts)
        self.assertIn(REFUND_NOT_STARS, texts)
        self.assertEqual(await self._payment_state("chg-home"), ("paid", "issued"))
        self.assertEqual(await self._payment_state("admin:abc", "admin_grant"), ("paid", "issued"))

        self.session.requests.clear()
        await self._feed_text(14, "/refund@ChassisBot 15 chg-home", 5)
        calls = self._named("RefundStarPayment")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].user_id, 15)
        self.assertEqual(calls[0].telegram_payment_charge_id, "chg-home")
        self.assertEqual(await self._payment_state("chg-home"), ("refunded", "cancelled"))
        self.assertTrue(any("Платёж возвращён: chg-home" in item.text for item in self._named("SendMessage") if item.chat_id == 14))
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(14, "/refund 15 chg-home", 6)
        self.assertFalse(self._named("RefundStarPayment"))
        self.assertIn(REFUND_ALREADY, [item.text for item in self._named("SendMessage") if item.chat_id == 14])

        await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=15,
            sku_code="audit",
            amount=10,
            telegram_payment_charge_id="chg-fail",
        )
        original = self.session.make_request

        async def fail_refund(bot, method, timeout=None):
            if method.__class__.__name__ == "RefundStarPayment":
                raise TelegramBadRequest(method=method, message="CHARGE_NOT_FOUND")
            return await original(bot, method, timeout)

        self.session.make_request = fail_refund
        self.session.requests.clear()
        await self._feed_text(14, "/refund 15 chg-fail", 7)
        self.assertEqual(await self._payment_state("chg-fail"), ("paid", "issued"))
        self.assertTrue(any("CHARGE_NOT_FOUND" in item.text for item in self._named("SendMessage") if item.chat_id == 14))

        self.session.make_request = original
        self.session.requests.clear()
        await self.storage.users.set_ban("bot_a", 14, True, "blocked")
        await self._feed_text(14, "/refund 15 chg-fail", 8)
        self.assertFalse(self._named("RefundStarPayment"))
        self.assertFalse(self._named("SendMessage"))
        self.assertEqual(await self._payment_state("chg-fail"), ("paid", "issued"))

    async def test_maintenance_command_sets_and_clears_reason(self) -> None:
        await self._feed_text(5, "/maintenance on", 1)
        await self._feed_text(14, "/maintenance", 2)
        on, reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertFalse(on)
        self.assertIsNone(reason)
        self.assertEqual(
            [item.text for item in self._named("SendMessage") if item.chat_id == 14],
            ["Рубильник снят"],
        )
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(14, "/maintenance@ChassisBot on сервис <b>", 3)
        on, reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertTrue(on)
        self.assertEqual(reason, "сервис <b>")
        actor = [item.text for item in self._named("SendMessage") if item.chat_id == 14]
        self.assertIn("Рубильник опущен. Причина: сервис &lt;b&gt;", actor)
        audit = [item.text for item in self._named("SendMessage") if item.chat_id == -100]
        self.assertTrue(any("Рубильник опущен" in item and "&lt;b&gt;" in item for item in audit))
        self.assertTrue(all("<b>" not in item for item in audit))

        self.session.requests.clear()
        await self._feed_text(14, "/maintenance on", 4)
        on, reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertTrue(on)
        self.assertEqual(reason, "сервис <b>")

        self.session.requests.clear()
        await self._feed_text(14, "/maintenance maybe", 5)
        self.assertIn(MAINTENANCE_USAGE, [item.text for item in self._named("SendMessage") if item.chat_id == 14])
        on, _reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertTrue(on)
        self.assertFalse(any(item.chat_id == -100 for item in self._named("SendMessage")))

        self.session.requests.clear()
        await self._feed_text(14, "/maintenance off", 6)
        on, reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertFalse(on)
        self.assertIsNone(reason)
        self.assertTrue(any("Рубильник снят" in item.text for item in self._named("SendMessage") if item.chat_id == -100))

        self.session.requests.clear()
        await self.storage.users.set_ban("bot_a", 14, True, "blocked")
        await self._feed_text(14, "/maintenance on снова", 7)
        self.assertFalse(self._named("SendMessage"))
        on, reason = await self.storage.bot_settings.get_maintenance_status("bot_a")
        self.assertFalse(on)
        self.assertIsNone(reason)

    async def test_broadcast_preview_delivery_and_stop(self) -> None:
        self.assertEqual(
            {item.value for item in PendingInputKind},
            {"support_message", "custom_input"},
        )
        await self.storage.users.upsert_user("bot_a", 16)
        await self.storage.users.set_shadow_ban("bot_a", 16, True)
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        panel = Message(message_id=50, date=1, chat=Chat(id=14, type="private"), text="admin")
        with patch("bot_chassis.admin.broadcast.asyncio.sleep", fake_sleep):
            await self._feed_callback(5, "adm_bcast", 1, panel)
            self.assertFalse(self._named("SendMessage"))

            await self._feed_callback(14, "adm_bcast", 2, panel)
            await self._feed_text(14, "hello <b>", 3)
            preview = [item for item in self._named("SendMessage") if item.chat_id == 14 and "Предпросмотр" in item.text]
            self.assertEqual(len(preview), 1)
            self.assertIn("hello &lt;b&gt;", preview[0].text)
            self.assertNotIn("hello <b>", preview[0].text)
            self.assertFalse(any(item.chat_id == 100 and item.text == "hello <b>" for item in self._named("SendMessage")))

            self.session.requests.clear()
            await self._feed_callback(14, CB_BROADCAST_CANCEL, 4, panel)
            self.assertFalse(any(item.text == "hello <b>" for item in self._named("SendMessage")))

            await self._feed_callback(14, "adm_bcast", 5, panel)
            await self._feed_text(14, "hello <b>", 6)
            self.session.requests.clear()
            slept.clear()
            await self._feed_callback(14, CB_BROADCAST_GO, 7, panel)
            bodies = [item for item in self._named("SendMessage") if item.text == "hello <b>"]
            self.assertEqual(sorted(item.chat_id for item in bodies), [14, 100])
            status = [item for item in self._named("SendMessage") if item.text.startswith("📢 Рассылка:")]
            self.assertEqual(status[0].reply_markup.inline_keyboard[0][0].callback_data, CB_BROADCAST_STOP)
            self.assertNotIn(15, [item.chat_id for item in bodies])
            self.assertNotIn(16, [item.chat_id for item in bodies])
            self.assertIn(BROADCAST_INTERVAL, slept)
            self.assertTrue(any("Старт рассылки" in item.text for item in self._named("SendMessage") if item.chat_id == -100))
            self.assertTrue(any("Рассылка завершена" in item.text and "доставлено=2" in item.text for item in self._named("SendMessage") if item.chat_id == -100))
            self.assertTrue(any("Доставлено: 2" in item.text for item in self._named("EditMessageText")))

            await self.storage.users.upsert_user("bot_a", 17)
            original = self.session.make_request

            async def retry_once(bot, method, timeout=None):
                if method.__class__.__name__ == "SendMessage" and getattr(method, "chat_id", None) == 17 and getattr(method, "text", "") == "again":
                    if not retry_once.seen:
                        retry_once.seen = True
                        from aiogram.exceptions import TelegramRetryAfter

                        raise TelegramRetryAfter(method=method, message="flood", retry_after=2)
                return await original(bot, method, timeout)

            retry_once.seen = False
            self.session.make_request = retry_once
            self.session.requests.clear()
            slept.clear()
            await self._feed_callback(14, "adm_bcast", 8, panel)
            await self._feed_text(14, "again", 9)
            await self._feed_callback(14, CB_BROADCAST_GO, 10, panel)
            self.assertIn(2, slept)
            again = [item for item in self._named("SendMessage") if item.text == "again"]
            self.assertIn(17, [item.chat_id for item in again])
            self.session.make_request = original

            async def forbid_100(bot, method, timeout=None):
                if method.__class__.__name__ == "SendMessage" and getattr(method, "chat_id", None) == 100 and getattr(method, "text", "") == "quiet":
                    from aiogram.exceptions import TelegramForbiddenError

                    raise TelegramForbiddenError(method=method, message="blocked")
                return await original(bot, method, timeout)

            self.session.make_request = forbid_100
            self.session.requests.clear()
            await self._feed_callback(14, "adm_bcast", 11, panel)
            await self._feed_text(14, "quiet", 12)
            await self._feed_callback(14, CB_BROADCAST_GO, 13, panel)
            quiet = [item for item in self._named("SendMessage") if item.text == "quiet"]
            self.assertIn(14, [item.chat_id for item in quiet])
            self.assertNotIn(100, [item.chat_id for item in quiet])
            self.assertTrue(any("ошибок=1" in item.text for item in self._named("SendMessage") if item.chat_id == -100))
            self.session.make_request = original

            from bot_chassis.admin.broadcast import _BROADCAST_SESSIONS

            async def stop_after_actor(bot, method, timeout=None):
                result = await original(bot, method, timeout)
                if method.__class__.__name__ == "SendMessage" and getattr(method, "text", "") == "halt":
                    session = _BROADCAST_SESSIONS.get(14)
                    if session is not None:
                        session.cancel = True
                return result

            self.session.make_request = stop_after_actor
            self.session.requests.clear()
            await self._feed_callback(14, "adm_bcast", 14, panel)
            await self._feed_text(14, "halt", 15)
            await self._feed_callback(14, CB_BROADCAST_GO, 16, panel)
            halted = [item for item in self._named("SendMessage") if item.text == "halt"]
            self.assertEqual([item.chat_id for item in halted], [14])
            self.assertTrue(any("остановлено=2" in item.text for item in self._named("SendMessage") if item.chat_id == -100))
            self.session.make_request = original

            self.session.requests.clear()
            await self.storage.users.set_ban("bot_a", 14, True, "blocked")
            await self._feed_callback(14, "adm_bcast", 17, panel)
            self.assertFalse(self._named("SendMessage"))

    async def test_long_ban_reason_keeps_words_and_caps_length(self) -> None:
        await self.storage.users.upsert_user("bot_a", 16)
        reason = "слово " * 120
        await self._feed_text(14, f"/ban 16 {reason}", 1)
        stored = (await self.storage.users.get_user("bot_a", 16)).ban_reason
        self.assertEqual(len(stored), 500)
        self.assertTrue(stored.endswith("..."))
        self.assertTrue(stored.startswith("слово "))

    async def test_refund_by_charge_id_uses_canonical_ids_and_bot_scope(self) -> None:
        await self._feed_text(14, "/refund chg-home", 1)
        calls = self._named("RefundStarPayment")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].user_id, 15)
        self.assertEqual(calls[0].telegram_payment_charge_id, "chg-home")
        self.assertEqual(await self._payment_state("chg-home"), ("refunded", "cancelled"))

        await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=15,
            sku_code="vip",
            amount=10,
            telegram_payment_charge_id="chg-split",
            payment_id="pay-split",
        )
        self.session.requests.clear()
        await self._feed_text(14, "/refund 15 chg-split", 2)
        split = self._named("RefundStarPayment")
        self.assertEqual(split[0].user_id, 15)
        self.assertEqual(split[0].telegram_payment_charge_id, "chg-split")
        self.assertEqual(await self._payment_state("pay-split"), ("refunded", "cancelled"))
        self.assertTrue(
            any("Платёж возвращён: pay-split" in item.text for item in self._named("SendMessage") if item.chat_id == 14)
        )

        await self.storage.users.upsert_user("bot_b", 15)
        await self.storage.transactions.record_successful_payment(
            bot_id="bot_b",
            user_id=15,
            sku_code="vip",
            amount=10,
            telegram_payment_charge_id="chg-foreign",
            payment_id="pay-foreign",
        )
        self.session.requests.clear()
        await self._feed_text(14, "/refund chg-foreign", 3)
        self.assertFalse(self._named("RefundStarPayment"))
        self.assertIn(REFUND_NOT_FOUND, [item.text for item in self._named("SendMessage") if item.chat_id == 14])

    async def test_dossier_home_returns_to_admin_screen(self) -> None:
        panel = Message(message_id=50, date=1, chat=Chat(id=14, type="private"), text="dossier")
        await self._feed_callback(14, "adm_home", 1, panel)
        edited = self._named("EditMessageText")
        self.assertEqual(len(edited), 1)
        self.assertIn("Админка", edited[0].text)
        self.assertIn(CB_MAINT, [button.callback_data for row in edited[0].reply_markup.inline_keyboard for button in row])

    async def _payment_state(self, payment_id: str, provider: str = "telegram_stars") -> tuple[str, str] | None:
        def _op(conn):
            row = conn.execute(
                """
                SELECT status, voucher_status FROM transactions
                WHERE bot_id = ? AND provider = ? AND payment_id = ?
                """,
                ("bot_a", provider, payment_id),
            ).fetchone()
            if row is None:
                return None
            return row["status"], row["voucher_status"]

        return await self.storage.engine.run(_op)

    async def _active_gifts(self, user_id: int) -> int:
        def _op(conn) -> int:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM subscriptions
                WHERE bot_id = ? AND user_id = ? AND status = 'active'
                """,
                ("bot_a", user_id),
            ).fetchone()
            return int(row["n"])

        return await self.storage.engine.run(_op)

    async def _feed_command(self, user_id: int, update_id: int) -> None:
        await self._feed_text(user_id, "/admin", update_id)

    async def _feed_text(self, user_id: int, text: str, update_id: int) -> None:
        user = _user(user_id)
        message = Message(
            message_id=update_id,
            date=1,
            chat=Chat(id=user_id, type="private"),
            from_user=user,
            text=text,
        )
        await self.dp.feed_update(self.bot, Update(update_id=update_id, message=message))

    async def _feed_callback(
        self,
        user_id: int,
        data: str,
        update_id: int,
        panel: Message,
        username: str | None = None,
    ) -> None:
        user = _user(user_id, username=username)
        update = Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"c{update_id}",
                from_user=user,
                chat_instance="x",
                data=data,
                message=panel,
            ),
        )
        await self.dp.feed_update(self.bot, update)

    def _named(self, name: str) -> list[TelegramMethod]:
        return [item for item in self.session.requests if item.__class__.__name__ == name]


def _csv_rows(payload: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))


def _document(method: TelegramMethod) -> tuple[str, bytes]:
    return method.document.filename, method.document.data


def _user(user_id: int, username: str | None = None) -> User:
    return User(id=user_id, is_bot=False, first_name="N", username=username)


if __name__ == "__main__":
    unittest.main()
