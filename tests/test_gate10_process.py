"""Gate 10: ProcessControlPort, confirmation, controller last, no system commands."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from dataclasses import replace

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot_chassis.admin.broadcast import reset_broadcast_sessions
from bot_chassis.admin.lookup import reset_admin_lookups
from bot_chassis.admin.process import (
    CB_RST_ALL,
    RESTART_AUDIT_FAILED,
    PROCESS_CONTROL_UNAVAILABLE,
    RESTART_IN_FLIGHT,
    RESTART_STALE,
    reset_process_intents,
)
from bot_chassis.admin.router import SUPERADMIN_ONLY, create_admin_router
from bot_chassis.admin.screens import CB_GO_RESTART
from bot_chassis.config import BotChassisConfig
from bot_chassis.factory import create_complete_chassis
from bot_chassis.ports.process_control import (
    ProcessOperationResult,
    ProcessTarget,
    order_targets,
)
from bot_chassis.storage import create_storage


class _Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.fail_chat_ids: set[int] = set()

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.requests.append(method)
        name = method.__class__.__name__
        if name == "SendMessage" and getattr(method, "chat_id", None) in self.fail_chat_ids:
            raise RuntimeError("delivery failed")
        if name in {"SendMessage", "EditMessageText"}:
            return Message(
                message_id=getattr(method, "message_id", None) or len(self.requests),
                date=int(time.time()),
                chat=Chat(id=getattr(method, "chat_id", 0) or 14, type="private"),
                text=getattr(method, "text", "") or "",
            )
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536):
        yield b""


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="N")


class FakeProcessControl:
    def __init__(
        self,
        *,
        delay_for: str | None = None,
        hold: asyncio.Event | None = None,
        status_error_for: str | None = None,
    ) -> None:
        self.restarts: list[str] = []
        self.results: dict[str, ProcessOperationResult] = {}
        self.delay_for = delay_for
        self.hold = hold
        self.status_error_for = status_error_for
        self.behavior = {"alpha": "ok", "beta": "error", "hub": "timeout"}
        self.audit_seen_at_restart: list[bool] = []
        self.session: _Session | None = None

    async def list_targets(self):
        return [
            ProcessTarget("alpha", "Alpha", status="up"),
            ProcessTarget("hub", "Hub", is_controller=True, status="up"),
            ProcessTarget("beta", "Beta", status="up"),
        ]

    async def restart(self, target_id: str) -> ProcessOperationResult:
        if self.session is not None:
            texts = [getattr(item, "text", "") or "" for item in self.session.requests]
            self.audit_seen_at_restart.append(any("Рестарт запрошен" in text for text in texts))
        self.restarts.append(target_id)
        if self.hold is not None and target_id == self.delay_for:
            await self.hold.wait()
        elif self.delay_for == target_id:
            await asyncio.sleep(0.15)
        op_id = f"op-{target_id}-{len(self.restarts)}"
        status = self.behavior.get(target_id, "ok")
        result = ProcessOperationResult(op_id, target_id, status, status)
        self.results[op_id] = result
        return result

    async def restart_all(self):
        out = []
        for item in order_targets(await self.list_targets()):
            out.append(await self.restart(item.target_id))
        return out

    async def get_status(self, operation_id: str) -> ProcessOperationResult | None:
        result = self.results.get(operation_id)
        if result is not None and result.target_id == self.status_error_for:
            raise RuntimeError("status unavailable")
        return result


class TestOrderTargets(unittest.TestCase):
    def test_controller_is_last(self) -> None:
        ordered = order_targets(
            [
                ProcessTarget("hub", "Hub", is_controller=True),
                ProcessTarget("a", "A"),
                ProcessTarget("b", "B"),
            ]
        )
        self.assertEqual([item.target_id for item in ordered], ["a", "b", "hub"])


class TestGate10ProcessControl(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config = BotChassisConfig(
            bot_id="bot_a",
            db_path=os.path.join(self._tmp.name, "p.db"),
            superadmin_ids=(100,),
            audit_chat_id=-100,
            ops_thread_id=7,
        )
        self.storage = await create_storage(self.config)
        await self.storage.roles.grant_role("bot_a", 14, "admin", granted_by=100)
        reset_broadcast_sessions()
        reset_admin_lookups()
        reset_process_intents()
        self.session = _Session()
        self.bot = Bot(token="123456:ABC", session=self.session)
        self.port = FakeProcessControl()
        self.port.session = self.session
        self.dp = Dispatcher()
        self.dp.include_router(
            create_admin_router(
                "bot_a",
                self.storage,
                self.config,
                process_control=self.port,
            )
        )

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()
        reset_process_intents()
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

    def _confirm_data(self) -> str:
        for item in reversed(self._named("EditMessageText")):
            markup = getattr(item, "reply_markup", None)
            if markup is None:
                continue
            for row in markup.inline_keyboard:
                for button in row:
                    data = button.callback_data or ""
                    if data.startswith("adm_rst:ok:"):
                        return data
        self.fail("no confirm button")

    async def test_staff_hidden_and_denied(self) -> None:
        await self._command(14, 1)
        home = self._named("SendMessage")[0]
        callbacks = [button.callback_data for row in home.reply_markup.inline_keyboard for button in row]
        self.assertNotIn(CB_GO_RESTART, callbacks)
        self.session.requests.clear()
        await self._callback(14, CB_GO_RESTART, 2)
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, SUPERADMIN_ONLY)

    async def test_root_list_has_no_system_commands_and_shows_status(self) -> None:
        await self._command(100, 1)
        home = [item for item in self._named("SendMessage") if item.chat_id == 100][0]
        callbacks = [button.callback_data for row in home.reply_markup.inline_keyboard for button in row]
        self.assertIn(CB_GO_RESTART, callbacks)
        self.session.requests.clear()
        await self._callback(100, CB_GO_RESTART, 2)
        edited = self._named("EditMessageText")[0]
        blob = (edited.text or "").lower()
        self.assertIn("alpha", blob)
        self.assertIn("управляющий", edited.text.lower())
        self.assertNotIn("systemctl", blob)
        self.assertNotIn("docker", blob)
        labels = [button.text for row in edited.reply_markup.inline_keyboard for button in row]
        self.assertTrue(all("systemd" not in text.lower() for text in labels))
        self.assertIn(CB_RST_ALL, [button.callback_data for row in edited.reply_markup.inline_keyboard for button in row])

    async def test_one_restart_audits_before_port_and_reports(self) -> None:
        await self._callback(100, "adm_rst:t:alpha", 1)
        confirm = self._confirm_data()
        self.session.requests.clear()
        self.port.restarts.clear()
        self.port.audit_seen_at_restart.clear()
        await self._callback(100, confirm, 2)
        self.assertEqual(self.port.restarts, ["alpha"])
        self.assertTrue(self.port.audit_seen_at_restart[0])
        texts = [item.text or "" for item in self._named("SendMessage")]
        self.assertTrue(any("Рестарт запрошен" in text and "operation=" in text for text in texts))
        self.assertTrue(any("Alpha: ok" in (item.text or "") for item in self._named("SendMessage") if item.chat_id == -100))
        frozen = [item for item in self._named("EditMessageText") if item.reply_markup is None]
        self.assertTrue(any("ok=1" in (item.text or "") for item in frozen))
        self.assertTrue(any("Админка" in (item.text or "") for item in self._named("SendMessage") if item.chat_id == 100))

    async def test_restart_all_runs_controller_last_and_keeps_going(self) -> None:
        await self._callback(100, CB_RST_ALL, 1)
        confirm = self._confirm_data()
        await self._callback(100, confirm, 2)
        self.assertEqual(self.port.restarts, ["alpha", "beta", "hub"])
        report = "\n".join(item.text or "" for item in self._named("EditMessageText"))
        self.assertIn("error", report)
        self.assertIn("timeout", report)
        self.assertIn("ok=1", report)
        self.assertIn("error=1", report)
        self.assertIn("timeout=1", report)

    async def test_confirm_token_is_one_shot(self) -> None:
        await self._callback(100, "adm_rst:t:alpha", 1)
        confirm = self._confirm_data()
        await self._callback(100, confirm, 2)
        self.session.requests.clear()
        await self._callback(100, confirm, 3)
        self.assertEqual(self._named("AnswerCallbackQuery")[-1].text, RESTART_STALE)
        self.assertEqual(self.port.restarts, ["alpha"])

    async def test_parallel_same_target_is_rejected(self) -> None:
        hold = asyncio.Event()
        port = FakeProcessControl(delay_for="alpha", hold=hold)
        port.session = self.session
        dp = Dispatcher()
        dp.include_router(create_admin_router("bot_a", self.storage, self.config, process_control=port))
        self.dp = dp
        await self._callback(100, "adm_rst:t:alpha", 1)
        first = self._confirm_data()
        await self._callback(100, "adm_rst:t:alpha", 2)
        second = self._confirm_data()
        self.assertNotEqual(first, second)
        task = asyncio.create_task(self._callback(100, first, 3))
        for _ in range(50):
            if port.restarts:
                break
            await asyncio.sleep(0.02)
        await self._callback(100, second, 4)
        self.assertEqual(self._named("AnswerCallbackQuery")[-1].text, RESTART_IN_FLIGHT)
        hold.set()
        await task
        self.assertEqual(port.restarts, ["alpha"])

    async def test_restart_is_cancelled_without_audit_destination(self) -> None:
        config = replace(self.config, audit_chat_id=None)
        self.dp = Dispatcher()
        self.dp.include_router(
            create_admin_router("bot_a", self.storage, config, process_control=self.port)
        )
        await self._callback(100, "adm_rst:t:alpha", 1)
        confirm = self._confirm_data()
        self.session.requests.clear()
        await self._callback(100, confirm, 2)
        self.assertEqual(self.port.restarts, [])
        self.assertEqual(self._named("AnswerCallbackQuery")[-1].text, RESTART_AUDIT_FAILED)

    async def test_restart_is_cancelled_when_audit_delivery_fails(self) -> None:
        await self._callback(100, "adm_rst:t:alpha", 1)
        confirm = self._confirm_data()
        self.session.requests.clear()
        self.session.fail_chat_ids.add(-100)
        await self._callback(100, confirm, 2)
        self.assertEqual(self.port.restarts, [])
        self.assertEqual(self._named("AnswerCallbackQuery")[-1].text, RESTART_AUDIT_FAILED)

    async def test_status_failure_becomes_error_and_final_report_survives(self) -> None:
        port = FakeProcessControl(status_error_for="alpha")
        port.session = self.session
        self.dp = Dispatcher()
        self.dp.include_router(
            create_admin_router("bot_a", self.storage, self.config, process_control=port)
        )
        await self._callback(100, "adm_rst:t:alpha", 1)
        confirm = self._confirm_data()
        self.session.requests.clear()
        await self._callback(100, confirm, 2)
        self.assertEqual(port.restarts, ["alpha"])
        frozen = [item for item in self._named("EditMessageText") if item.reply_markup is None]
        self.assertTrue(any("error=1" in (item.text or "") for item in frozen))
        self.assertTrue(
            any("status check failed" in (item.text or "") for item in frozen)
        )

    async def test_factory_without_port_hides_restart(self) -> None:
        chassis = await create_complete_chassis(self.bot, self.config)
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=90,
                message=Message(
                    message_id=90,
                    date=1,
                    chat=Chat(id=100, type="private"),
                    from_user=_user(100),
                    text="/admin",
                ),
            ),
        )
        homes = [item for item in self._named("SendMessage") if item.chat_id == 100 and "Админка" in (item.text or "")]
        callbacks = [button.callback_data for row in homes[-1].reply_markup.inline_keyboard for button in row]
        self.assertNotIn(CB_GO_RESTART, callbacks)
        self.session.requests.clear()
        await chassis.dp.feed_update(
            self.bot,
            Update(
                update_id=91,
                callback_query=CallbackQuery(
                    id="91",
                    from_user=_user(100),
                    chat_instance="x",
                    data=CB_GO_RESTART,
                    message=Message(message_id=50, date=1, chat=Chat(id=100, type="private"), text="x"),
                ),
            ),
        )
        self.assertEqual(self._named("AnswerCallbackQuery")[0].text, PROCESS_CONTROL_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
