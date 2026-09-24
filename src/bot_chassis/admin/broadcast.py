"""Рассылка: свой RAM-store, 25 сообщений/с, остановка без FSM кнопок."""

from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from ..config import BotChassisConfig
from ..storage import Storage
from .audit import send_admin_audit

CB_BROADCAST = "adm_bcast"
CB_BROADCAST_GO = "adm_bcast:go"
CB_BROADCAST_CANCEL = "adm_bcast:cancel"
CB_BROADCAST_STOP = "adm_bcast:stop"
BROADCAST_INTERVAL = 1 / 25
BROADCAST_PROGRESS_EVERY = 25
BROADCAST_PROMPT = "Пришлите текст рассылки."
_RETRY_LIMIT = 5

_BROADCAST_SESSIONS: dict[int, "BroadcastSession"] = {}
_BROADCAST_LOCK = asyncio.Lock()


@dataclass
class BroadcastSession:
    phase: str
    text: str = ""
    cancel: bool = False


def reset_broadcast_sessions() -> None:
    global _BROADCAST_LOCK
    _BROADCAST_SESSIONS.clear()
    _BROADCAST_LOCK = asyncio.Lock()


def register_broadcast(router: Router, bot_id: str, storage: Storage, config: BotChassisConfig, staff: Filter) -> None:
    @router.callback_query(F.data == CB_BROADCAST, staff)
    async def start_broadcast(call: CallbackQuery) -> None:
        actor = call.from_user
        if actor is None or await _is_banned(storage, bot_id, actor.id):
            await call.answer()
            return
        current = _BROADCAST_SESSIONS.get(actor.id)
        if current is not None and current.phase == "running":
            await call.answer("Рассылка уже идёт", show_alert=True)
            return
        _BROADCAST_SESSIONS[actor.id] = BroadcastSession(phase="awaiting")
        await call.bot.send_message(actor.id, BROADCAST_PROMPT)
        await call.answer()

    @router.message(AwaitingBroadcastText(), staff)
    async def capture_broadcast_text(message: Message) -> None:
        actor = message.from_user
        if actor is None or await _is_banned(storage, bot_id, actor.id):
            return
        session = _BROADCAST_SESSIONS.get(actor.id)
        if session is None or session.phase != "awaiting":
            return
        text = (message.text or "").strip()
        if text == "/cancel":
            _BROADCAST_SESSIONS.pop(actor.id, None)
            await message.answer("Рассылка отменена")
            return
        if not text:
            await message.answer(BROADCAST_PROMPT)
            return
        session.phase = "preview"
        session.text = message.text or ""
        await message.answer(
            "📢 Предпросмотр\n" + html.escape(session.text),
            parse_mode="HTML",
            reply_markup=_preview_keyboard(),
        )

    @router.callback_query(F.data == CB_BROADCAST_CANCEL, staff)
    async def cancel_broadcast(call: CallbackQuery) -> None:
        actor = call.from_user
        if actor is None or await _is_banned(storage, bot_id, actor.id):
            await call.answer()
            return
        _BROADCAST_SESSIONS.pop(actor.id, None)
        await call.answer("Рассылка отменена")

    @router.callback_query(F.data == CB_BROADCAST_GO, staff)
    async def launch_broadcast(call: CallbackQuery) -> None:
        actor = call.from_user
        if actor is None or await _is_banned(storage, bot_id, actor.id):
            await call.answer()
            return
        session = _BROADCAST_SESSIONS.get(actor.id)
        if session is None or session.phase != "preview" or not session.text:
            await call.answer("Нет текста рассылки", show_alert=True)
            return
        session.phase = "running"
        session.cancel = False
        await call.answer()
        try:
            await _run_broadcast(call.bot, storage, config, bot_id, actor.id, session)
        finally:
            _BROADCAST_SESSIONS.pop(actor.id, None)

    @router.callback_query(F.data == CB_BROADCAST_STOP, staff)
    async def stop_broadcast(call: CallbackQuery) -> None:
        actor = call.from_user
        if actor is None:
            await call.answer()
            return
        session = _BROADCAST_SESSIONS.get(actor.id)
        if session is None or session.phase != "running":
            await call.answer()
            return
        session.cancel = True
        await call.answer("Останавливаю рассылку")


class AwaitingBroadcastText(Filter):
    async def __call__(self, message: Message) -> bool:
        actor = message.from_user
        if actor is None:
            return False
        session = _BROADCAST_SESSIONS.get(actor.id)
        return session is not None and session.phase == "awaiting"


def _preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data=CB_BROADCAST_GO)],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data=CB_BROADCAST_CANCEL)],
        ]
    )


def _stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🛑 Экстренно остановить", callback_data=CB_BROADCAST_STOP)]]
    )


async def _run_broadcast(bot, storage: Storage, config: BotChassisConfig, bot_id: str, actor_id: int, session: BroadcastSession) -> None:
    async with _BROADCAST_LOCK:
        recipients = await storage.users.get_broadcast_user_ids(bot_id)
        total = len(recipients)
        await send_admin_audit(bot, config, f"Старт рассылки. user_id={actor_id} получателей={total}")
        status = await bot.send_message(
            actor_id,
            f"📢 Рассылка: 0/{total}",
            reply_markup=_stop_keyboard(),
        )
        delivered = 0
        errors = 0
        stopped = 0
        for index, user_id in enumerate(recipients):
            if session.cancel:
                stopped = total - index
                break
            if index > 0 and index % BROADCAST_PROGRESS_EVERY == 0:
                await _edit_progress(bot, actor_id, status.message_id, delivered, errors, total)
            outcome = await _send_one(bot, user_id, session.text)
            if outcome == "delivered":
                delivered += 1
            else:
                errors += 1
            if index + 1 < total and not session.cancel:
                await asyncio.sleep(BROADCAST_INTERVAL)
        title = "📢 Рассылка остановлена" if session.cancel else "📢 Рассылка завершена"
        report = f"{title}\nДоставлено: {delivered}\nОшибок: {errors}\nОстановлено: {stopped}"
        await _edit_progress(bot, actor_id, status.message_id, delivered, errors, total, report=report)
        state = "остановлена" if session.cancel else "завершена"
        await send_admin_audit(
            bot,
            config,
            f"Рассылка {state}. доставлено={delivered} ошибок={errors} остановлено={stopped}. user_id={actor_id}",
        )


async def _send_one(bot, user_id: int, text: str) -> str:
    factor = 1
    for _attempt in range(_RETRY_LIMIT):
        try:
            await bot.send_message(user_id, text)
            return "delivered"
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after * factor)
            factor *= 2
        except TelegramForbiddenError:
            return "error"
        except Exception:
            logger.exception(f"Рассылка не доставлена user_id={user_id}")
            return "error"
    return "error"


async def _edit_progress(bot, actor_id: int, message_id: int, delivered: int, errors: int, total: int, report: str | None = None) -> None:
    text = report or f"📢 Рассылка: {delivered + errors}/{total}"
    markup = None if report else _stop_keyboard()
    try:
        await bot.edit_message_text(text, chat_id=actor_id, message_id=message_id, reply_markup=markup)
    except Exception:
        logger.exception("Не удалось обновить прогресс рассылки")


async def _is_banned(storage: Storage, bot_id: str, user_id: int) -> bool:
    user = await storage.users.get_user(bot_id, user_id)
    return bool(user and user.is_banned)
