"""Этап 2: порты, мидлвари и смена языка. Кнопки и storage-тесты не заменяет."""

from __future__ import annotations

import inspect
import os
import tempfile
import time
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InaccessibleMessage,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
    Update,
    User,
)

from bot_chassis.config import BotChassisConfig
from bot_chassis.localization import create_localization_router
from bot_chassis.middleware.error_monitor import ErrorAlertMiddleware
from bot_chassis.middleware.throttling import ThrottlingMiddleware
from bot_chassis.middleware.user_activity import UserActivityMiddleware
from bot_chassis.ports.access import DefaultAccessAdapter
from bot_chassis.ports.cabinet import build_cabinet_renderer
from bot_chassis.ports.cabinet import DefaultCabinetSlotsAdapter
from bot_chassis.ports.payments import DefaultVoucherManagerAdapter
from bot_chassis.ports.work_gate import DefaultWorkGateAdapter
from bot_chassis.router import create_button_chassis_router
from bot_chassis.storage import create_storage
from bot_chassis.storage.engine import parse_utc, utc_now


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
                message_id=999,
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0), type="private"),
                text=getattr(method, "text", ""),
            )
        return True

    async def stream_content(self, url: str, headers: dict | None = None, timeout: int = 30, chunk_size: int = 65536):
        yield b""


def _user(user_id: int, language_code: str = "ru", username: str | None = None) -> User:
    return User(
        id=user_id,
        is_bot=False,
        first_name="N",
        language_code=language_code,
        username=username,
    )


def _message(user: User, text: str | None = "hi", payment: SuccessfulPayment | None = None) -> Message:
    return Message(
        message_id=user.id,
        date=1,
        chat=Chat(id=user.id, type="private"),
        from_user=user,
        text=text,
        successful_payment=payment,
    )


def _stars_payment(charge_id: str = "chg") -> SuccessfulPayment:
    return SuccessfulPayment(
        currency="XTR",
        total_amount=1,
        invoice_payload="sku:audit:1:abcd",
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id="prov",
    )


class TestPortsAndMiddleware(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "chassis.db")
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=self.db_path,
            superadmin_ids=(100,),
        )
        self.storage = await create_storage(self.config)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_work_gate_adapter(self) -> None:
        gate = DefaultWorkGateAdapter(self.storage.bot_settings, self.storage.users)
        await self.storage.users.upsert_user("bot_a", 5, username="ann")

        ok, reason = await gate.can_accept_work("bot_a", 5)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        await self.storage.bot_settings.set_maintenance_status("bot_a", True, reason="pause", updated_by=100)
        await self.storage.users.set_shadow_ban("bot_a", 5, True)
        ok, reason = await gate.can_accept_work("bot_a", 5)
        self.assertFalse(ok)
        self.assertEqual(reason, "pause")
        await self.storage.bot_settings.set_maintenance_status("bot_a", False, updated_by=100)

        await self.storage.users.set_ban("bot_a", 5, True, "spam")
        ok, reason = await gate.can_accept_work("bot_a", 5)
        self.assertFalse(ok)
        self.assertIsNone(reason)

        await self.storage.users.set_shadow_ban("bot_a", 5, False)
        ok, reason = await gate.can_accept_work("bot_a", 5)
        self.assertFalse(ok)
        self.assertEqual(reason, "spam")

        await self.storage.users.set_ban("bot_a", 5, False)
        ok, reason = await gate.can_accept_work("bot_a", 5)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    async def test_access_adapter_invariants(self) -> None:
        access = DefaultAccessAdapter(self.storage.subscriptions)

        ok, err = await access.grant_gift_access("bot_a", 50, granted_by=100, days=None)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIsNotNone(await self.storage.users.get_user("bot_a", 50))
        sub = await self.storage.subscriptions.get_active_subscription("bot_a", 50)
        self.assertEqual(sub.plan_code, "default")
        self.assertTrue(sub.is_lifetime)
        self.assertIsNone(sub.expires_at)
        self.assertEqual(sub.granted_by, 100)
        self.assertTrue(await access.has_active_access("bot_a", 50))

        ok, err = await access.grant_gift_access("bot_a", 50, granted_by=100, days=30)
        self.assertTrue(ok)
        timed = await self.storage.subscriptions.get_active_subscription("bot_a", 50)
        self.assertFalse(timed.is_lifetime)
        self.assertIsNotNone(timed.expires_at)
        self.assertNotEqual(sub.id, timed.id)
        self.assertTrue(await access.has_active_access("bot_a", 50))

        past = (parse_utc(utc_now()) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        def _expire(conn) -> None:
            conn.execute(
                """
                UPDATE subscriptions SET expires_at = ?
                WHERE bot_id = ? AND user_id = ? AND status = 'active'
                """,
                (past, "bot_a", 50),
            )

        await self.storage.engine.run(_expire)
        self.assertFalse(await access.has_active_access("bot_a", 50))

        ok, err = await access.grant_gift_access("bot_a", 50, granted_by=100, days=30)
        self.assertTrue(ok)
        ok, err = await access.revoke_gift_access("bot_a", 50)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertFalse(await access.has_active_access("bot_a", 50))

        await self.storage.users.upsert_user("bot_a", 51)
        await self.storage.users.set_ban("bot_a", 51, True, "x")
        ok, err = await access.grant_gift_access("bot_a", 51, granted_by=100, days=7)
        self.assertTrue(ok)
        self.assertTrue(await access.has_active_access("bot_a", 51))

        ok, err = await access.grant_gift_access("bot_a", 52, granted_by=100, days=-1)
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_days")

    async def test_voucher_manager_adapter(self) -> None:
        await self.storage.users.upsert_user("bot_a", 7)
        await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=7,
            sku_code="audit",
            amount=50,
            telegram_payment_charge_id="chg-1",
        )
        vouchers = DefaultVoucherManagerAdapter(self.storage.transactions)
        active = await vouchers.get_active_vouchers("bot_a", 7, sku_code="audit")
        self.assertEqual(len(active), 1)
        voucher = active[0]
        self.assertEqual(voucher.payment_id, "chg-1")
        self.assertEqual(voucher.amount, 50)
        self.assertIsInstance(voucher.amount, int)
        self.assertEqual(voucher.status, "issued")
        self.assertIsNone(voucher.redeemed_at)

        ok, err = await vouchers.redeem_voucher("bot_a", 7, voucher.voucher_id)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(await vouchers.get_active_vouchers("bot_a", 7), [])
        ok, err = await vouchers.redeem_voucher("bot_a", 7, voucher.voucher_id)
        self.assertFalse(ok)
        self.assertEqual(err, "already_redeemed")

    async def test_cabinet_slots_adapter(self) -> None:
        await self.storage.users.upsert_user("bot_a", 8, username="ann<b>")
        user = await self.storage.users.get_user("bot_a", 8)
        cabinet = DefaultCabinetSlotsAdapter(
            self.storage.subscriptions,
            self.storage.transactions,
            users_repo=self.storage.users,
            referrals_repo=self.storage.referrals,
            bot_username="ChassisBot",
            enable_payments=True,
            enable_referrals=True,
        )
        slots = {slot.slot_id: slot for slot in await cabinet.get_cabinet_slots("bot_a", 8)}
        self.assertIn(f"ID: 8 | @ann<b> | Зарегистрирован: {user.created_at[:10]}", slots["profile"].content)
        self.assertEqual(slots["access"].content, "Доступ: Базовый")
        self.assertEqual(slots["vouchers"].content, "🎟 Доступно талонов: 0")
        self.assertIn("Приглашено друзей: 0", slots["referrals"].content)

        await self.storage.subscriptions.grant_gift_access("bot_a", 8, granted_by=100, days=None)
        slots = {slot.slot_id: slot for slot in await cabinet.get_cabinet_slots("bot_a", 8)}
        self.assertEqual(slots["access"].content, "🎁 Доступ: VIP (Бессрочно)")

        await self.storage.subscriptions.grant_gift_access("bot_a", 8, granted_by=100, days=30)
        sub = await self.storage.subscriptions.get_active_subscription("bot_a", 8)
        slots = {slot.slot_id: slot for slot in await cabinet.get_cabinet_slots("bot_a", 8)}
        self.assertEqual(slots["access"].content, f"🎁 Доступ: VIP (до {sub.expires_at[:10]})")

        await self.storage.transactions.record_successful_payment(
            bot_id="bot_a",
            user_id=8,
            sku_code="audit",
            amount=10,
            telegram_payment_charge_id="chg-cab",
        )
        await self.storage.referrals.record_referral("bot_a", 8, 80)
        slots = {slot.slot_id: slot for slot in await cabinet.get_cabinet_slots("bot_a", 8)}
        self.assertEqual(slots["vouchers"].content, "🎟 Доступно талонов: 1")
        self.assertIn("https://t.me/ChassisBot?start=ref_8", slots["referrals"].content)
        self.assertIn("Приглашено друзей: 1", slots["referrals"].content)

        hidden = DefaultCabinetSlotsAdapter(
            self.storage.subscriptions,
            self.storage.transactions,
            users_repo=self.storage.users,
            referrals_repo=self.storage.referrals,
            bot_username="ChassisBot",
            enable_payments=False,
            enable_referrals=False,
        )
        hidden_ids = [slot.slot_id for slot in await hidden.get_cabinet_slots("bot_a", 8)]
        self.assertNotIn("vouchers", hidden_ids)
        self.assertNotIn("referrals", hidden_ids)

        renderer = build_cabinet_renderer(cabinet, "bot_a")
        expected = inspect.signature(create_button_chassis_router).parameters["render_cabinet_callback"].annotation
        self.assertEqual(list(inspect.signature(renderer).parameters), ["message", "user_id", "bot"])
        self.assertIn("Message", str(expected))
        message = AsyncMock()
        message.answer = AsyncMock(return_value="sent")
        self.assertEqual(await renderer(message, 8, AsyncMock()), "sent")
        text = message.answer.await_args.args[0]
        self.assertIn("@ann&lt;b&gt;", text)
        self.assertNotIn("@ann<b>", text)
        self.assertEqual(message.answer.await_args.kwargs["parse_mode"], "HTML")

    async def test_throttling_middleware(self) -> None:
        clock = {"t": 10_000.0}

        def _now() -> float:
            return clock["t"]

        user = SimpleNamespace(id=7)
        other = SimpleNamespace(id=8)
        cb_user = _user(7)
        callback = Update(
            update_id=1,
            callback_query=CallbackQuery(id="cb", from_user=cb_user, chat_instance="x", data="x"),
        )
        payment = Update(
            update_id=2,
            pre_checkout_query=PreCheckoutQuery(
                id="pq",
                from_user=cb_user,
                currency="XTR",
                total_amount=1,
                invoice_payload="sku:audit:7:abcd",
            ),
        )
        calls = {"n": 0}

        async def handler(event, data):
            calls["n"] += 1
            return "ok"

        with patch("bot_chassis.middleware.throttling.time.monotonic", _now):
            mw = ThrottlingMiddleware("bot_a")
            self.assertEqual(mw._bot_id, "bot_a")
            with patch.object(CallbackQuery, "answer", new_callable=AsyncMock) as answer:
                for _ in range(5):
                    self.assertEqual(await mw(handler, callback, {"event_from_user": user}), "ok")
                self.assertEqual(calls["n"], 5)
                self.assertIsNone(await mw(handler, callback, {"event_from_user": user}))
                self.assertEqual(calls["n"], 5)
                answer.assert_awaited_with("⚠️ Слишком часто! Пожалуйста, помедленнее.", show_alert=False)
                self.assertEqual(await mw(handler, payment, {"event_from_user": user}), "ok")
                self.assertEqual(calls["n"], 6)
                self.assertIsNone(await mw(handler, callback, {"event_from_user": user}))
                self.assertIn(("bot_a", 7), mw._hits)

                self.assertEqual(await mw(handler, callback, {"event_from_user": other}), "ok")
                self.assertIn(("bot_a", 8), mw._hits)
                clock["t"] = 10_001.0
                self.assertEqual(await mw(handler, callback, {"event_from_user": user}), "ok")
                self.assertIn(("bot_a", 8), mw._hits)
                clock["t"] = 10_061.0
                self.assertEqual(await mw(handler, callback, {"event_from_user": user}), "ok")
                self.assertNotIn(("bot_a", 8), mw._hits)
                self.assertIn(("bot_a", 7), mw._hits)

    async def test_error_monitor_middleware(self) -> None:
        user = _user(3)
        pre = Update(
            update_id=1,
            pre_checkout_query=PreCheckoutQuery(
                id="pq",
                from_user=user,
                currency="XTR",
                total_amount=1,
                invoice_payload="x",
            ),
        )
        calls = {"n": 0}

        async def boom(event, data):
            calls["n"] += 1
            raise RuntimeError("bad <script>")

        off = ErrorAlertMiddleware(BotChassisConfig(bot_id="bot_a", enable_error_alerts=False))
        with self.assertRaises(RuntimeError):
            await off(boom, pre, {})
        self.assertEqual(calls["n"], 1)

        bot = AsyncMock()
        silent = ErrorAlertMiddleware(BotChassisConfig(bot_id="bot_a", support_chat_id=None))
        with patch.object(PreCheckoutQuery, "answer", new_callable=AsyncMock) as answer:
            self.assertIsNone(await silent(boom, pre, {"bot": bot}))
        answer.assert_awaited()
        self.assertFalse(answer.await_args.kwargs["ok"])
        self.assertEqual(answer.await_args.kwargs["error_message"], "⚠️ Ошибка при обработке платежа.")
        bot.send_message.assert_not_awaited()
        self.assertEqual(calls["n"], 2)

        bot.send_message = AsyncMock(side_effect=RuntimeError("net"))
        alerting = ErrorAlertMiddleware(BotChassisConfig(bot_id="bot_a", support_chat_id=-100))
        with patch.object(PreCheckoutQuery, "answer", new_callable=AsyncMock):
            self.assertIsNone(await alerting(boom, pre, {"bot": bot}))
        self.assertEqual(calls["n"], 3)
        text = bot.send_message.await_args.args[1]
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)
        self.assertEqual(bot.send_message.await_args.kwargs["parse_mode"], "HTML")

    async def test_user_activity_middleware_language_retention(self) -> None:
        await self.storage.users.upsert_user("bot_a", 9, language_code="en")
        await self.storage.users.set_language_code("bot_a", 9, "en")
        cache: dict[int, str] = {}
        mw = UserActivityMiddleware("bot_a", self.storage, self.config, locale_cache=cache)
        tg = _user(9, language_code="ru", username="neo")
        called = AsyncMock(return_value="ok")
        result = await mw(called, Update(update_id=1, message=_message(tg, "hi")), {"event_from_user": tg})
        self.assertEqual(result, "ok")
        saved = await self.storage.users.get_user("bot_a", 9)
        self.assertEqual(saved.language_code, "en")
        self.assertEqual(cache[9], "en")

    async def test_user_activity_middleware_shadow_ban_silent_drop(self) -> None:
        await self.storage.users.upsert_user("bot_a", 11, username="old")
        await self.storage.users.set_shadow_ban("bot_a", 11, True)
        mw = UserActivityMiddleware("bot_a", self.storage, self.config)
        tg = _user(11, username="new")
        called = AsyncMock(return_value="ok")
        message = Update(update_id=1, message=_message(tg, "hi"))
        self.assertIsNone(await mw(called, message, {"event_from_user": tg}))
        called.assert_not_awaited()
        saved = await self.storage.users.get_user("bot_a", 11)
        self.assertEqual(saved.username, "new")
        self.assertTrue(saved.is_shadow_banned)

        callback = Update(
            update_id=2,
            callback_query=CallbackQuery(id="cb", from_user=tg, chat_instance="x", data="x"),
        )
        with patch.object(CallbackQuery, "answer", new_callable=AsyncMock) as answer:
            self.assertIsNone(await mw(called, callback, {"event_from_user": tg}))
        answer.assert_awaited_with()
        called.assert_not_awaited()

    async def test_user_activity_middleware_shadow_ban_payment_pass(self) -> None:
        await self.storage.users.upsert_user("bot_a", 12)
        await self.storage.users.set_shadow_ban("bot_a", 12, True)
        mw = UserActivityMiddleware("bot_a", self.storage, self.config)
        tg = _user(12)
        called = AsyncMock(return_value="ok")
        pre = Update(
            update_id=1,
            pre_checkout_query=PreCheckoutQuery(
                id="pq",
                from_user=tg,
                currency="XTR",
                total_amount=1,
                invoice_payload="x",
            ),
        )
        paid = Update(update_id=2, message=_message(tg, text=None, payment=_stars_payment()))
        self.assertEqual(await mw(called, pre, {"event_from_user": tg}), "ok")
        self.assertEqual(await mw(called, paid, {"event_from_user": tg}), "ok")
        self.assertEqual(called.await_count, 2)

    async def test_user_activity_middleware_shadow_ban_admin_immunity(self) -> None:
        await self.storage.users.upsert_user("bot_a", 14)
        await self.storage.users.set_shadow_ban("bot_a", 14, True)
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)

        def _shadow_superadmin(conn) -> None:
            conn.execute(
                "UPDATE users SET is_shadow_banned = 1 WHERE bot_id = ? AND user_id = ?",
                ("bot_a", 100),
            )

        await self.storage.engine.run(_shadow_superadmin)
        mw = UserActivityMiddleware("bot_a", self.storage, self.config)
        called = AsyncMock(return_value="ok")
        admin = _user(14)
        root = _user(100)
        self.assertEqual(
            await mw(called, Update(update_id=1, message=_message(admin, "hi")), {"event_from_user": admin}),
            "ok",
        )
        self.assertEqual(
            await mw(called, Update(update_id=2, message=_message(root, "hi")), {"event_from_user": root}),
            "ok",
        )
        self.assertEqual(called.await_count, 2)
        self.assertTrue((await self.storage.users.get_user("bot_a", 14)).is_shadow_banned)
        self.assertTrue((await self.storage.users.get_user("bot_a", 100)).is_shadow_banned)

    async def test_user_activity_middleware_referrals(self) -> None:
        cfg = BotChassisConfig(bot_id="bot_a", db_path=self.db_path, enable_referrals=True)
        mw = UserActivityMiddleware("bot_a", self.storage, cfg)
        called = AsyncMock(return_value="ok")

        async def start(user_id: int, text: str, update_id: int) -> None:
            tg = _user(user_id)
            await mw(called, Update(update_id=update_id, message=_message(tg, text)), {"event_from_user": tg})

        await start(201, "/start ref_123", 1)
        self.assertEqual(await self.storage.referrals.get_referrals_count("bot_a", 123), 1)
        self.assertEqual((await self.storage.users.get_user("bot_a", 201)).traffic_source, "ref_123")

        await start(201, "/start utm_later", 2)
        self.assertEqual((await self.storage.users.get_user("bot_a", 201)).traffic_source, "ref_123")
        self.assertEqual(await self.storage.referrals.get_referrals_count("bot_a", 123), 1)

        await start(202, "/start ref_invalid_abc", 3)
        self.assertEqual((await self.storage.users.get_user("bot_a", 202)).traffic_source, "ref_invalid_abc")

        def _referee_rows(conn):
            return conn.execute(
                "SELECT COUNT(*) AS n FROM referrals WHERE bot_id = ? AND referee_id = ?",
                ("bot_a", 202),
            ).fetchone()["n"]

        self.assertEqual(int(await self.storage.engine.run(_referee_rows)), 0)

        await start(203, "/start@BotName ref_1", 4)
        self.assertEqual(await self.storage.referrals.get_referrals_count("bot_a", 1), 1)
        self.assertEqual((await self.storage.users.get_user("bot_a", 203)).traffic_source, "ref_1")

    async def test_localization_router(self) -> None:
        await self.storage.users.upsert_user("bot_a", 9, language_code="ru")
        session = _Session()
        bot = Bot(token="123456:ABC", session=session)
        dp = Dispatcher()
        cache: dict[int, str] = {}
        dp.include_router(
            create_localization_router(
                "bot_a",
                self.storage,
                enabled=True,
                locale_cache=cache,
                domain_rows=[["Ваши чаты", "Ваши слова"]],
                enable_support=False,
            )
        )
        user = _user(9)
        chat = Chat(id=9, type="private")
        message = Message(message_id=1, date=1, chat=chat, from_user=user, text="x")

        async def feed(data: str, update_id: int, target: Message | InaccessibleMessage = message) -> None:
            update = Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"c{update_id}",
                    from_user=user,
                    chat_instance="x",
                    data=data,
                    message=target,
                ),
            )
            await dp.feed_update(bot, update)

        await feed("core_lang:de", 1)
        self.assertEqual((await self.storage.users.get_user("bot_a", 9)).language_code, "ru")
        self.assertNotIn("SendMessage", [item.__class__.__name__ for item in session.requests])

        session.requests.clear()
        await feed("core_lang:en", 2)
        names = [item.__class__.__name__ for item in session.requests]
        self.assertIn("SendMessage", names)
        self.assertNotIn("EditMessageText", names)
        self.assertEqual(cache[9], "en")
        self.assertEqual((await self.storage.users.get_user("bot_a", 9)).language_code, "en")
        sent = next(item for item in session.requests if item.__class__.__name__ == "SendMessage")
        rows = [[button.text for button in row] for row in sent.reply_markup.keyboard]
        self.assertEqual(rows[0], ["Ваши чаты", "Ваши слова"])
        self.assertIn("Account", rows[1][0])
        self.assertTrue(all("Support" not in text and "Поддержка" not in text for row in rows for text in row))

        session.requests.clear()
        ghost = InaccessibleMessage(chat=chat, message_id=1)
        await feed("core_lang:ru", 3, ghost)
        self.assertEqual([item.__class__.__name__ for item in session.requests], ["AnswerCallbackQuery"])
        self.assertEqual((await self.storage.users.get_user("bot_a", 9)).language_code, "ru")
        await bot.session.close()


if __name__ == "__main__":
    unittest.main()
