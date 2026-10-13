"""Экраны рестарта: одноразовый токен, без параллели на одну цель, аудит до первого вызова."""

from __future__ import annotations

import asyncio
import html
import re
import secrets
import uuid
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from ..config import BotChassisConfig
from ..ports.process_control import (
    ProcessControlPort,
    ProcessOperationResult,
    ProcessTarget,
    order_targets,
)
from ..service_notify import deliver_service_message, resolve_service_destination
from .audit import send_admin_audit
from .screens import CB_GO_RESTART, nav_keyboard

CB_RST_ALL = "adm_rst:all"
CB_RST_NO = "adm_rst:no"
CB_RST_PREFIX_ONE = "adm_rst:t:"
CB_RST_PREFIX_OK = "adm_rst:ok:"
PROCESS_CONTROL_UNAVAILABLE = "Управление процессами не подключено"
RESTART_IN_FLIGHT = "Этот процесс уже перезапускается"
RESTART_STALE = "Подтверждение устарело"
RESTART_UNKNOWN = "Цель не найдена"
RESTART_AUDIT_FAILED = "Рестарт отменён: не удалось записать аудит"
_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")

_INTENTS: dict[str, "RestartIntent"] = {}
_BUSY: set[str] = set()
_BUSY_LOCK = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class RestartIntent:
    token: str
    actor_id: int
    kind: str
    target_ids: tuple[str, ...]


def reset_process_intents() -> None:
    global _BUSY_LOCK
    _INTENTS.clear()
    _BUSY.clear()
    _BUSY_LOCK = asyncio.Lock()


def register_process_control(
    router: Router,
    *,
    bot_id: str,
    config: BotChassisConfig,
    staff: Filter,
    root: Filter,
    panels,
    process_control: ProcessControlPort | None,
    raise_home,
    require_root_call,
) -> None:
    _ = root
    @router.callback_query(F.data == CB_GO_RESTART, staff)
    async def handle_restart_screen(call: CallbackQuery) -> None:
        user = await require_root_call(call, "Рестарт бота")
        if user is None:
            return
        if process_control is None:
            await call.answer(PROCESS_CONTROL_UNAVAILABLE, show_alert=True)
            return
        await _show_list(call, bot_id, user.id, process_control, panels)
        await call.answer()

    if process_control is None:
        return

    @router.callback_query(F.data == CB_RST_ALL, staff)
    async def ask_restart_all(call: CallbackQuery) -> None:
        user = await require_root_call(call, "Рестарт бота")
        if user is None:
            return
        targets = order_targets(await process_control.list_targets())
        if not targets:
            await call.answer(RESTART_UNKNOWN, show_alert=True)
            return
        token = _store_intent(user.id, "all", tuple(item.target_id for item in targets))
        names = ", ".join(html.escape(item.label) for item in targets)
        await panels.edit_or_send(
            call,
            bot_id,
            user.id,
            "Перезапустить все процессы по очереди?\n"
            "Управляющий процесс будет последним.\n" + names,
            _confirm_keyboard(token),
        )
        await call.answer()

    @router.callback_query(F.data.startswith(CB_RST_PREFIX_ONE), staff)
    async def ask_restart_one(call: CallbackQuery) -> None:
        user = await require_root_call(call, "Рестарт бота")
        if user is None:
            return
        target_id = (call.data or "").removeprefix(CB_RST_PREFIX_ONE)
        target = await _find_target(process_control, target_id)
        if target is None:
            await call.answer(RESTART_UNKNOWN, show_alert=True)
            return
        token = _store_intent(user.id, "one", (target.target_id,))
        await panels.edit_or_send(
            call,
            bot_id,
            user.id,
            f"Перезапустить {html.escape(target.label)}?",
            _confirm_keyboard(token),
        )
        await call.answer()

    @router.callback_query(F.data == CB_RST_NO, staff)
    async def cancel_restart(call: CallbackQuery) -> None:
        user = await require_root_call(call, "Рестарт бота")
        if user is None:
            return
        await _show_list(call, bot_id, user.id, process_control, panels)
        await call.answer("Отменено")

    @router.callback_query(F.data.startswith(CB_RST_PREFIX_OK), staff)
    async def confirm_restart(call: CallbackQuery) -> None:
        user = await require_root_call(call, "Рестарт бота")
        if user is None:
            return
        token = (call.data or "").removeprefix(CB_RST_PREFIX_OK)
        intent = _INTENTS.pop(token, None)
        if intent is None or intent.actor_id != user.id:
            await call.answer(RESTART_STALE, show_alert=True)
            return
        claimed = await _claim(intent.target_ids)
        if not claimed:
            await call.answer(RESTART_IN_FLIGHT, show_alert=True)
            return
        operation_id = uuid.uuid4().hex
        try:
            await _run_restart(
                call,
                bot_id=bot_id,
                config=config,
                actor_id=user.id,
                operation_id=operation_id,
                intent=intent,
                process_control=process_control,
                panels=panels,
                raise_home=raise_home,
            )
        finally:
            await _release(intent.target_ids)


async def _run_restart(
    call: CallbackQuery,
    *,
    bot_id: str,
    config: BotChassisConfig,
    actor_id: int,
    operation_id: str,
    intent: RestartIntent,
    process_control: ProcessControlPort,
    panels,
    raise_home,
) -> None:
    known = {item.target_id: item for item in await process_control.list_targets()}
    ordered_ids = list(intent.target_ids)
    if intent.kind == "all":
        ordered_ids = [item.target_id for item in order_targets(list(known.values()))]
        ordered_ids = [item for item in ordered_ids if item in set(intent.target_ids)]
    # Последовательный restart(), не port.restart_all(): нужен ops после каждой цели.
    labels = [known[item].label if item in known else item for item in ordered_ids]
    audit_sent = await send_admin_audit(
        call.bot,
        config,
        "Рестарт запрошен. "
        f"actor={actor_id} targets={','.join(ordered_ids)} operation={operation_id}",
    )
    if not audit_sent:
        await panels.edit_or_send(
            call,
            bot_id,
            actor_id,
            RESTART_AUDIT_FAILED,
            nav_keyboard(),
        )
        await call.answer(RESTART_AUDIT_FAILED, show_alert=True)
        return
    await call.answer("Запускаю…")
    lines = [f"Рестарт operation={operation_id}"]
    results: list[ProcessOperationResult] = []
    for target_id in ordered_ids:
        label = html.escape(known[target_id].label if target_id in known else target_id)
        try:
            result = await process_control.restart(target_id)
            try:
                fetched = await process_control.get_status(result.operation_id)
            except Exception as exc:
                logger.exception("Порт рестарта не вернул статус операции")
                result = ProcessOperationResult(
                    operation_id=result.operation_id,
                    target_id=target_id,
                    status="error",
                    detail=("status check failed: " + str(exc))[:200],
                )
            else:
                if fetched is not None:
                    result = fetched
        except Exception as exc:
            logger.exception("Порт рестарта вернул исключение")
            result = ProcessOperationResult(
                operation_id=operation_id,
                target_id=target_id,
                status="error",
                detail=str(exc)[:200],
            )
        results.append(result)
        line = f"{label}: {result.status}"
        if result.detail:
            line += " — " + html.escape(result.detail)
        lines.append(line)
        await _send_ops(call.bot, config, f"Рестарт {label}: {result.status}. operation={operation_id}")
        await panels.edit_or_send(
            call,
            bot_id,
            actor_id,
            "\n".join(lines),
            nav_keyboard(),
        )
    ok_n = sum(1 for item in results if item.status == "ok")
    err_n = sum(1 for item in results if item.status == "error")
    timeout_n = sum(1 for item in results if item.status == "timeout")
    title = "Рестарт завершён" if err_n == 0 and timeout_n == 0 else "Рестарт с ошибками"
    report = (
        f"{title}\noperation={operation_id}\n"
        f"цели: {', '.join(html.escape(name) for name in labels)}\n"
        + "\n".join(lines[1:])
        + f"\nитог: ok={ok_n} error={err_n} timeout={timeout_n}"
    )
    await _send_ops(call.bot, config, report)
    await panels.freeze_as_report(call, bot_id, actor_id, report)
    await raise_home(call.bot, actor_id, True, int(call.bot.id))


async def _show_list(call: CallbackQuery, bot_id: str, actor_id: int, port: ProcessControlPort, panels) -> None:
    targets = order_targets(await port.list_targets())
    if not targets:
        await panels.edit_or_send(
            call,
            bot_id,
            actor_id,
            "🔄 Рестарт\nЦелей нет. Рама не хранит имена процессов.",
            nav_keyboard(),
        )
        return
    lines = ["🔄 Рестарт", "Рама вызывает внешний порт. Системных команд в пакете нет."]
    rows: list[list[InlineKeyboardButton]] = []
    for item in targets:
        mark = " (управляющий)" if item.is_controller else ""
        state = f" — {item.status}" if item.status else ""
        lines.append(f"• {html.escape(item.label)}{mark}{html.escape(state)}")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Рестарт: {item.label}"[:64],
                    callback_data=CB_RST_PREFIX_ONE + item.target_id,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Рестарт всех", callback_data=CB_RST_ALL)])
    await panels.edit_or_send(
        call,
        bot_id,
        actor_id,
        "\n".join(lines),
        nav_keyboard(*rows),
    )


def _confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return nav_keyboard(
        [
            InlineKeyboardButton(text="Подтвердить", callback_data=CB_RST_PREFIX_OK + token),
            InlineKeyboardButton(text="Отмена", callback_data=CB_RST_NO),
        ]
    )


def _store_intent(actor_id: int, kind: str, target_ids: tuple[str, ...]) -> str:
    token = secrets.token_hex(8)
    _INTENTS[token] = RestartIntent(token=token, actor_id=actor_id, kind=kind, target_ids=target_ids)
    return token


async def _find_target(port: ProcessControlPort, target_id: str) -> ProcessTarget | None:
    if not _TARGET_ID_RE.fullmatch(target_id):
        return None
    for item in await port.list_targets():
        if item.target_id == target_id:
            return item
    return None


async def _claim(target_ids: tuple[str, ...]) -> bool:
    async with _BUSY_LOCK:
        if any(item in _BUSY for item in target_ids):
            return False
        _BUSY.update(target_ids)
        return True


async def _release(target_ids: tuple[str, ...]) -> None:
    async with _BUSY_LOCK:
        for item in target_ids:
            _BUSY.discard(item)


async def _send_ops(bot, config: BotChassisConfig, text: str) -> None:
    try:
        await deliver_service_message(
            bot,
            resolve_service_destination(config, "ops"),
            text,
        )
    except Exception:
        logger.exception("Не удалось отправить ops-итог рестарта")
