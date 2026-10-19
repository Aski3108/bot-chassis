"""Экран /admin, команды и рассылка."""

from __future__ import annotations

import html
import inspect
import math
import os
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.types import BufferedInputFile, FSInputFile
from loguru import logger

from ..followup import (
    AdminSanctionKind,
    PendingInput,
    PendingInputKind,
    PendingInputStore,
    PendingScope,
)
from ..config import BotChassisConfig, resolved_origin
from ..policies import BACKUP_JOB_KEY, UTC_PLUS_5
from ..ports.admin_extra import ExtraAdminActions
from ..storage.backup import write_manual_snapshot
from ..storage import Storage
from ..storage.engine import parse_utc
from .audit import format_sanction_audit, send_admin_audit
from .broadcast import is_awaiting_broadcast_text, register_broadcast
from .lookup import (
    FIND_CANCELLED,
    FIND_PROMPT,
    SANCTION_STALE,
    SANCTION_TARGET_MISMATCH,
    AwaitingAdminBanReason,
    AwaitingAdminLookup,
    begin_admin_lookup,
    cancel_admin_lookup,
)
from .user_resolve import format_ambiguous_users, resolve_user_token
from .export import EXPORT_SCOPES, XLSX_FILENAME, build_export, build_xlsx_export
from .filters import AdminRoleFilter, SuperadminRoleFilter
from .process import register_process_control
from .screens import (
    CB_BACK,
    CB_DO_BACKUP,
    CB_DO_MAINT,
    CB_GO_BCAST,
    CB_GO_DB,
    CB_GO_MAINT,
    CB_GO_STATS,
    DB_MENU_TEXT,
    AdminScreenTracker,
    back_only_keyboard,
    db_menu_keyboard,
    home_keyboard,
    nav_keyboard,
)

CB_MAINT = "adm_maint"
CB_EXPORT = "adm_export"
CB_BROADCAST = "adm_bcast"
CB_HOME = "adm_home"
CB_FIND = "adm_find"
USERS_PAGE_SIZE = 15
BAN_USAGE = "Формат: /ban ID|@username [причина]"
UNBAN_USAGE = "Формат: /unban ID|@username"
SHADOW_USAGE = "Формат: /shadowban ID|@username 0|1"
USER_NOT_FOUND = "Пользователь не найден"
LAST_SUPERADMIN = "Нельзя забанить последнего суперадмина"
TARGET_IS_ADMIN = "Нельзя наложить тень на admin или superadmin"
GRANT_USAGE = "Формат: /grant ID|@username role"
REVOKE_USAGE = "Формат: /revoke ID|@username role"
INVALID_ROLE = "Неизвестная роль. Допустимо: admin, superadmin"
ALREADY_GRANTED = "Роль уже выдана"
ROLE_NOT_FOUND = "Роль не найдена"
LAST_SUPERADMIN_ROLE = "Нельзя снять роль последнего суперадмина"
GIFT_USAGE = "Формат: /gift ID|@username [days]"
GIFT_REVOKE_USAGE = "Формат: /gift_revoke ID|@username"
GIFT_NOT_FOUND = "Активный подарок не найден"
USER_USAGE = "Формат: /user ID|@username"
EXPORT_USAGE = "Формат: /export [users|payments|gifts|all]"
BACKUP_USAGE = "Формат: /backup"
BACKUP_TOO_LARGE = "Снапшот больше 50 МБ, файл не отправлен."
BACKUP_LIMIT_BYTES = 50 * 1024 * 1024
REFUND_USAGE = "Формат: /refund charge_id или /refund user_id payment_id"
REFUND_NOT_FOUND = "Платёж не найден"
REFUND_NOT_STARS = "Возврат доступен только для платежей Stars"
REFUND_ALREADY = "Платёж уже возвращён"
REFUND_NO_CHARGE = "У платежа нет идентификатора Stars"
REFUND_REJECTED = "Telegram не подтвердил возврат"
REFUND_OTHER_BOT = "Платёж принял другой бот; откройте /refund в нём"
SECURITY_ALERT_TTL_SECONDS = 60.0
_SECURITY_ALERT_THROTTLE: dict[tuple[str, int, str], float] = {}


def _drop_expired_security_alerts(now: float) -> None:
    expired = [
        key
        for key, seen_at in _SECURITY_ALERT_THROTTLE.items()
        if now - seen_at >= SECURITY_ALERT_TTL_SECONDS
    ]
    for key in expired:
        del _SECURITY_ALERT_THROTTLE[key]


MAINTENANCE_USAGE = (
    "Формат: /maintenance [on|off] [причина] или /maintenance bot_id on|off [причина]. "
    "Локальная пауза останавливает опросники этого бота, но не отключает Stars."
)


def create_admin_router(
    bot_id: str,
    storage: Storage,
    config: BotChassisConfig,
    extra_actions: ExtraAdminActions | None = None,
    *,
    extra_user_dossier_lines=None,
    extra_user_dossier_rows=None,
    bot_display_name_provider=None,
    pending_store=None,
    backup_policy=None,
    reporting_policy=None,
    screens: AdminScreenTracker | None = None,
    process_control=None,
) -> Router:
    router = Router(name="admin")
    resolved_pending_store = pending_store or PendingInputStore()
    staff = AdminRoleFilter(bot_id, storage.roles)
    root = SuperadminRoleFilter(bot_id, storage.roles)
    panels = screens or AdminScreenTracker()

    async def _send_sanction_audit(source, action: str, target_id: int, reason: str | None = None) -> None:
        target = await storage.users.get_user(bot_id, target_id)
        actor = source.from_user
        if target is None or actor is None:
            return
        await send_admin_audit(
            source.bot,
            config,
            format_sanction_audit(
                action,
                target_id=target_id,
                target_username=target.username,
                actor_id=actor.id,
                actor_username=actor.username,
                reason=reason,
            ),
            is_html=True,
        )

    async def _actor_is_root(user_id: int) -> bool:
        return await storage.roles.has_any_role(bot_id, user_id, ("superadmin",))

    async def _home_bundle(actor_id: int, telegram_bot_id: int) -> tuple[str, InlineKeyboardMarkup]:
        is_root = await _actor_is_root(actor_id)
        return await _home(
            storage,
            bot_id,
            extra_actions,
            is_root=is_root,
            telegram_bot_id=telegram_bot_id,
            process_control=process_control,
        )

    async def _raise_home(bot, actor_id: int, is_root: bool, telegram_bot_id: int) -> None:
        text, markup = await _home(
            storage,
            bot_id,
            extra_actions,
            is_root=is_root,
            telegram_bot_id=telegram_bot_id,
            process_control=process_control,
        )
        await panels.send_panel(bot, bot_id, actor_id, text, markup)

    async def _show_home_call(call: CallbackQuery, actor_id: int) -> None:
        text, markup = await _home_bundle(actor_id, int(call.bot.id))
        await panels.edit_or_send(call, bot_id, actor_id, text, markup)

    @router.message(Command("admin", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_admin(message: Message) -> None:
        user = message.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            return
        resolved_pending_store.clear(user.id, scope=PendingScope.ADMIN)
        text, markup = await _home_bundle(user.id, int(message.bot.id))
        await panels.send_panel(message.bot, bot_id, user.id, text, markup)

    @router.message(Command("ban", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_ban(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if not args:
            await _reply(message, BAN_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], BAN_USAGE)
        if target_id is None:
            return
        reason = " ".join(args[1:]).strip() or None
        reason = _clip_reason(reason) if reason else None
        ok, err = await storage.users.set_ban(bot_id, target_id, True, reason)
        if not ok:
            await _reply(message, _ban_error(err))
            return
        await _send_sanction_audit(message, "ban", target_id, reason)
        await _reply(message, f"Пользователь {target_id} забанен")

    @router.message(Command("unban", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_unban(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if len(args) != 1:
            await _reply(message, UNBAN_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], UNBAN_USAGE)
        if target_id is None:
            return
        ok, err = await storage.users.set_ban(bot_id, target_id, False)
        if not ok:
            await _reply(message, _ban_error(err))
            return
        await _send_sanction_audit(message, "unban", target_id)
        await _reply(message, f"Пользователь {target_id} разбанен")

    @router.message(Command("shadowban", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_shadowban(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        flag = args[1] if len(args) > 1 else ""
        if len(args) != 2 or flag not in {"0", "1"}:
            await _reply(message, SHADOW_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], SHADOW_USAGE)
        if target_id is None:
            return
        enabled = flag == "1"
        ok, err = await storage.users.set_shadow_ban(bot_id, target_id, enabled)
        if not ok:
            await _reply(message, _shadow_error(err))
            return
        state = "включён" if enabled else "снят"
        await _send_sanction_audit(message, "shadow_on" if enabled else "shadow_off", target_id)
        await _reply(message, f"Теневой бан {state}: {target_id}")

    @router.message(Command("grant", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_grant(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if len(args) != 2:
            await _reply(message, GRANT_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], GRANT_USAGE)
        if target_id is None:
            return
        role = args[1]
        ok, err = await storage.roles.grant_role(bot_id, target_id, role, granted_by=actor.id)
        if not ok:
            await _reply(message, _grant_error(err))
            return
        await send_admin_audit(
            message.bot,
            config,
            f"Роль {role} выдана user_id={target_id}. actor={actor.id}",
        )
        await _reply(message, f"Роль {role} выдана: {target_id}")

    @router.message(Command("revoke", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_revoke(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if len(args) != 2:
            await _reply(message, REVOKE_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], REVOKE_USAGE)
        if target_id is None:
            return
        role = args[1]
        ok, err = await storage.roles.revoke_role(bot_id, target_id, role)
        if not ok:
            await _reply(message, _revoke_error(err))
            return
        await send_admin_audit(
            message.bot,
            config,
            f"Роль {role} снята user_id={target_id}. actor={actor.id}",
        )
        await _reply(message, f"Роль {role} снята: {target_id}")

    @router.message(Command("gift", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_gift(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        parsed = _parse_gift_shape(message)
        if parsed is None:
            await _reply(message, GIFT_USAGE)
            return
        token, days = parsed
        target_id = await _target_from_token(message, storage, bot_id, token, GIFT_USAGE)
        if target_id is None:
            return
        ok, err = await storage.subscriptions.grant_gift_access(
            bot_id, target_id, granted_by=actor.id, days=days
        )
        if not ok:
            await _reply(message, GIFT_USAGE if err == "invalid_days" else GIFT_NOT_FOUND)
            return
        span = "бессрочно" if days is None or days == 0 else f"{days} дн."
        await send_admin_audit(
            message.bot,
            config,
            f"Подарок выдан user_id={target_id} ({span}). actor={actor.id}",
        )
        await _reply(message, f"Подарок выдан {span}: {target_id}")

    @router.message(Command("gift_revoke", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_gift_revoke(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if len(args) != 1:
            await _reply(message, GIFT_REVOKE_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], GIFT_REVOKE_USAGE)
        if target_id is None:
            return
        ok, _err = await storage.subscriptions.revoke_gift_access(bot_id, target_id)
        if not ok:
            await _reply(message, GIFT_NOT_FOUND)
            return
        await send_admin_audit(
            message.bot,
            config,
            f"Подарок отозван user_id={target_id}. actor={actor.id}",
        )
        await _reply(message, f"Подарок отозван: {target_id}")

    @router.message(Command("user", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_user(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if len(args) != 1:
            await _reply(message, USER_USAGE)
            return
        target_id = await _target_from_token(message, storage, bot_id, args[0], USER_USAGE)
        if target_id is None:
            return
        card = await _dossier(
            storage,
            bot_id,
            target_id,
            extra_user_dossier_lines=extra_user_dossier_lines,
            extra_user_dossier_rows=extra_user_dossier_rows,
            bot_display_name_provider=bot_display_name_provider,
            telegram_bot_id=int(message.bot.id),
            is_root=await _actor_is_root(actor.id),
        )
        if card is None:
            await _reply(message, USER_NOT_FOUND)
            return
        text, markup = card
        await panels.send_panel(message.bot, bot_id, actor.id, text, markup)

    async def _show_sanctions_call(call, actor_id: int, target_id: int) -> bool:
        card = await _dossier(
            storage,
            bot_id,
            target_id,
            extra_user_dossier_lines=extra_user_dossier_lines,
            extra_user_dossier_rows=extra_user_dossier_rows,
            bot_display_name_provider=bot_display_name_provider,
            telegram_bot_id=int(call.bot.id),
            is_root=await _actor_is_root(actor_id),
        )
        profile = await storage.users.get_user(bot_id, target_id)
        if card is None or profile is None:
            return False
        text, _base_markup = card
        await panels.edit_or_send(call, bot_id, actor_id, text, _sanctions_keyboard(profile))
        return True

    async def _show_subscription_call(call, actor_id: int, target_id: int) -> bool:
        card = await _dossier(
            storage,
            bot_id,
            target_id,
            extra_user_dossier_lines=extra_user_dossier_lines,
            extra_user_dossier_rows=extra_user_dossier_rows,
            bot_display_name_provider=bot_display_name_provider,
            telegram_bot_id=int(call.bot.id),
            is_root=True,
        )
        if card is None:
            return False
        text, _base_markup = card
        active = await storage.subscriptions.get_active_subscription(bot_id, target_id)
        await panels.edit_or_send(
            call,
            bot_id,
            actor_id,
            text,
            _subscription_keyboard(target_id, has_subscription=active is not None),
        )
        return True

    async def _apply_subscription(call, action: str, target_id: int) -> str | None:
        actor_id = call.from_user.id
        if action == "gift30":
            ok, _err = await storage.subscriptions.grant_gift_access(
                bot_id, target_id, granted_by=actor_id, days=30
            )
            if not ok:
                return GIFT_NOT_FOUND
            await send_admin_audit(call.bot, config, f"Подарок выдан user_id={target_id} (30 дн.). actor={actor_id}")
            return None
        if action == "giftlife":
            ok, _err = await storage.subscriptions.grant_gift_access(
                bot_id, target_id, granted_by=actor_id, days=None
            )
            if not ok:
                return GIFT_NOT_FOUND
            await send_admin_audit(call.bot, config, f"Подарок выдан user_id={target_id} (бессрочно). actor={actor_id}")
            return None
        if action == "revoke":
            ok, _err = await storage.subscriptions.revoke_gift_access(bot_id, target_id)
            if not ok:
                return GIFT_NOT_FOUND
            await send_admin_audit(call.bot, config, f"Подарок отозван user_id={target_id}. actor={actor_id}")
            return None
        if action == "token":
            payment_id = f"admin:{uuid.uuid4()}"
            _record, created = await storage.transactions.record_successful_payment(
                bot_id=bot_id,
                user_id=target_id,
                sku_code="admin_grant",
                amount=0,
                telegram_payment_charge_id=payment_id,
                provider="admin_grant",
                payment_id=payment_id,
                currency="XTR",
            )
            if created:
                await send_admin_audit(
                    call.bot,
                    config,
                    f"Талон выдан user_id={target_id} payment_id={payment_id}. actor={actor_id}",
                )
            return None
        return None

    @router.callback_query(F.data.startswith("adm_usr:menu:subscription:"), staff)
    async def handle_subscription_menu(call: CallbackQuery) -> None:
        actor = await _require_root_call(call, "🎁 Управление подпиской")
        if actor is None:
            return
        target_id = _parse_subscription_entry(call.data or "")
        if target_id is None:
            await call.answer()
            return
        shown = await _show_subscription_call(call, actor.id, target_id)
        if not shown:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        await call.answer()

    @router.callback_query(F.data.startswith("adm_usr:sub:"), staff)
    async def handle_subscription_action(call: CallbackQuery) -> None:
        parsed = _parse_subscription_callback(call.data or "")
        if parsed is None:
            await call.answer()
            return
        action, target_id = parsed
        actor = await _require_root_call(call, _SUBSCRIPTION_ACTION_LABELS[action])
        if actor is None:
            return
        if await storage.users.get_user(bot_id, target_id) is None:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        error = await _apply_subscription(call, action, target_id)
        if error:
            await call.answer(error, show_alert=True)
            return
        shown = await _show_subscription_call(call, actor.id, target_id)
        if not shown:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        await call.answer()

    async def _open_user_screen(call, actor_id: int, target_id: int, *, sanctions: bool) -> None:
        if await storage.users.get_user(bot_id, target_id) is None:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        shown = (
            await _show_sanctions_call(call, actor_id, target_id)
            if sanctions
            else await _show_dossier_call(call, actor_id, target_id, keyboard_mode="legacy")
        )
        if not shown:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        await call.answer()

    @router.callback_query(F.data.startswith("adm_usr:menu:"), staff)
    async def handle_dossier_menu(call: CallbackQuery) -> None:
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
            return
        parsed = _parse_menu_callback(call.data or "")
        if parsed is None:
            await call.answer()
            return
        kind, target_id = parsed
        if kind == "dossier":
            resolved_pending_store.clear(user.id, scope=PendingScope.ADMIN)
        await _open_user_screen(call, user.id, target_id, sanctions=kind == "sanctions")

    @router.callback_query(F.data.startswith("adm_usr:sanction:"), staff)
    async def handle_sanction_action(call: CallbackQuery) -> None:
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
            return
        parsed = _parse_sanction_callback(call.data or "")
        if parsed is None:
            await call.answer()
            return
        action, target_id = parsed
        if action in {"no_reason", "cancel"}:
            await _close_sanction_reason(call, user.id, target_id, action)
            return
        if await storage.users.get_user(bot_id, target_id) is None:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        if action in {"ban", "shadow_on"}:
            await _begin_sanction_reason(call, user.id, target_id, action)
            return
        error = await _apply_sanction(call, storage, config, bot_id, action, target_id)
        if error:
            await call.answer(error, show_alert=True)
            return
        shown = await _show_sanctions_call(call, user.id, target_id)
        if not shown:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        await call.answer()

    async def _begin_sanction_reason(call, actor_id: int, target_id: int, action: str) -> None:
        message = call.message
        if message is None or isinstance(message, InaccessibleMessage):
            await call.answer("Сообщение недоступно", show_alert=True)
            return
        profile = await storage.users.get_user(bot_id, target_id)
        if profile is None:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        kind = AdminSanctionKind.BAN if action == "ban" else AdminSanctionKind.SHADOW_BAN
        resolved_pending_store.set(
            actor_id,
            PendingInput(
                kind=PendingInputKind.ADMIN_BAN_REASON,
                target_user_id=target_id,
                origin_chat_id=message.chat.id,
                origin_message_id=message.message_id,
                sanction_kind=kind,
            ),
            scope=PendingScope.ADMIN,
        )
        await panels.edit_or_send(
            call,
            bot_id,
            actor_id,
            _sanction_prompt(profile, kind),
            _sanction_reason_keyboard(target_id),
        )
        await call.answer()

    async def _close_sanction_reason(call, actor_id: int, target_id: int, action: str) -> None:
        pending = resolved_pending_store.get(
            actor_id,
            PendingInputKind.ADMIN_BAN_REASON,
            scope=PendingScope.ADMIN,
        )
        if pending is None or pending.sanction_kind is None:
            await call.answer(SANCTION_STALE, show_alert=True)
            return
        if pending.target_user_id != target_id:
            await call.answer(SANCTION_TARGET_MISMATCH, show_alert=True)
            return
        resolved_pending_store.clear(actor_id, scope=PendingScope.ADMIN)
        if action == "no_reason":
            error = await _apply_named_sanction(call, pending.sanction_kind, target_id, "Не указана")
            if error:
                await call.answer(error, show_alert=True)
                return
        shown = await _show_dossier_call(call, actor_id, target_id, keyboard_mode="legacy")
        if not shown:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        await call.answer()

    async def _apply_named_sanction(source, kind: AdminSanctionKind, target_id: int, reason: str) -> str | None:
        actor_id = source.from_user.id
        if kind is AdminSanctionKind.BAN:
            ok, err = await storage.users.set_ban(bot_id, target_id, True, reason)
            if not ok:
                return _ban_error(err)
            await _send_sanction_audit(source, "ban", target_id, reason)
            return None
        ok, err = await storage.users.set_shadow_ban(bot_id, target_id, True, reason)
        if not ok:
            return _shadow_error(err)
        await _send_sanction_audit(source, "shadow_on", target_id, reason)
        return None

    async def _show_dossier_call(call, actor_id: int, target_id: int, *, keyboard_mode: str = "legacy") -> bool:
        if keyboard_mode != "legacy":
            keyboard_mode = "legacy"
        card = await _dossier(
            storage,
            bot_id,
            target_id,
            extra_user_dossier_lines=extra_user_dossier_lines,
            extra_user_dossier_rows=extra_user_dossier_rows,
            bot_display_name_provider=bot_display_name_provider,
            telegram_bot_id=int(call.bot.id),
            is_root=await _actor_is_root(actor_id),
        )
        if card is None:
            return False
        text, markup = card
        await panels.edit_or_send(call, bot_id, actor_id, text, markup)
        return True

    @router.callback_query(F.data.startswith("adm_usr:"), staff)
    async def handle_user_action(call: CallbackQuery) -> None:
        await call.answer()

    async def _show_users_page(call: CallbackQuery, actor_id: int, origin: str, page: int) -> None:
        total = await storage.users.count_users(bot_id)
        total_pages = max(1, math.ceil(total / USERS_PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        users = await storage.users.list_users_page(
            bot_id, limit=USERS_PAGE_SIZE, offset=page * USERS_PAGE_SIZE
        )
        text, markup = await _users_page_card(storage, bot_id, users, total, page, total_pages, origin)
        await panels.edit_or_send(call, bot_id, actor_id, text, markup)

    @router.callback_query(F.data.startswith("adm_users:p:"), staff)
    async def handle_users_page(call: CallbackQuery) -> None:
        parsed = _parse_users_page_callback(call.data or "")
        if parsed is None:
            await call.answer()
            return
        origin, page = parsed
        actor = await _require_staff_call(call)
        if actor is None:
            return
        if origin == "d" and await _require_root_call(call, "База данных") is None:
            return
        await _show_users_page(call, actor.id, origin, page)
        await call.answer()

    @router.callback_query(F.data.startswith("adm_users:o:"), staff)
    async def handle_users_open(call: CallbackQuery) -> None:
        target_id = _parse_users_open_callback(call.data or "")
        if target_id is None:
            await call.answer()
            return
        actor = await _require_staff_call(call)
        if actor is None:
            return
        shown = await _show_dossier_call(call, actor.id, target_id)
        await call.answer() if shown else await call.answer(USER_NOT_FOUND, show_alert=True)

    @router.message(Command("export", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_export_command(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        scope = args[0] if len(args) == 1 else ""
        if len(args) > 1 or (args and scope not in EXPORT_SCOPES):
            await _reply(message, EXPORT_USAGE)
            return
        await _send_export(message.bot, storage, config, bot_id, actor.id, scope or "all")

    @router.message(Command("backup", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_backup(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        if _command_args(message):
            await _reply(message, BACKUP_USAGE)
            return
        await _send_backup(message.bot, storage, actor.id, backup_policy=backup_policy)

    @router.message(Command("refund", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_refund(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        if len(args) == 1:
            target_id = None
            query = args[0]
        elif len(args) == 2:
            target_id = _parse_user_id(args[0])
            query = args[1]
            if target_id is None:
                await _reply(message, REFUND_USAGE)
                return
        else:
            await _reply(message, REFUND_USAGE)
            return
        row = await _find_payment(storage, bot_id, target_id, query, message.bot.id)
        if row is None:
            await _reply(message, REFUND_NOT_FOUND)
            return
        (
            canon_user_id,
            canon_payment_id,
            canon_charge_id,
            provider,
            status,
            voucher_status,
            merchant_origin_bot_id,
            merchant_telegram_bot_id,
        ) = row
        if provider != "telegram_stars":
            await _reply(message, REFUND_NOT_STARS)
            return
        if status == "refunded" or voucher_status == "cancelled":
            await _reply(message, REFUND_ALREADY)
            return
        if not canon_charge_id:
            await _reply(message, REFUND_NO_CHARGE)
            return
        if merchant_origin_bot_id != resolved_origin(config):
            await send_admin_audit(
                message.bot,
                config,
                "Несовпадение merchant origin при refund: "
                f"stored={merchant_origin_bot_id or 'legacy'} "
                f"current={resolved_origin(config)} payment_id={canon_payment_id}",
            )
        legacy_single_bot = merchant_telegram_bot_id == 0 and config.origin_bot_id is None
        if not legacy_single_bot and merchant_telegram_bot_id != message.bot.id:
            await _reply(message, REFUND_OTHER_BOT)
            return
        try:
            confirmed = await message.bot.refund_star_payment(
                user_id=canon_user_id,
                telegram_payment_charge_id=canon_charge_id,
            )
        except TelegramAPIError as exc:
            await _reply(message, str(exc))
            return
        if not confirmed:
            await _reply(message, REFUND_REJECTED)
            return
        ok, err = await storage.transactions.mark_refunded(
            bot_id,
            canon_payment_id,
            provider="telegram_stars",
            merchant_telegram_bot_id=merchant_telegram_bot_id,
        )
        if not ok:
            await _reply(message, _refund_mark_error(err))
            return
        await _reply(message, f"Платёж возвращён: {canon_payment_id}")

    @router.message(Command("maintenance", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_maintenance_command(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        current, reason = await storage.bot_settings.get_maintenance_status(bot_id)
        origin_bot_id = config.origin_bot_id
        current_origin = resolved_origin(config)
        if not args:
            if origin_bot_id is not None and current_origin != bot_id:
                local, local_reason = await storage.bot_settings.get_maintenance_status(
                    current_origin
                )
                await _reply(
                    message,
                    f"Сеть: {_maintenance_text(current, reason)}\n"
                    f"{current_origin}: {_maintenance_text(local, local_reason)}",
                )
                return
            await _reply(message, _maintenance_text(current, reason))
            return
        flag = args[0]
        if flag == "off" and len(args) == 1:
            await _set_maintenance(message, storage, config, bot_id, actor, False, None)
            return
        if flag == "on":
            new_reason = " ".join(args[1:]).strip() or reason
            await _set_maintenance(message, storage, config, bot_id, actor, True, new_reason)
            return
        if origin_bot_id is not None and len(args) >= 2 and args[1] in {"on", "off"}:
            requested_origin = args[0]
            if requested_origin != current_origin:
                await _reply(message, f"Этот бот = {current_origin}")
                return
            local_current, local_reason = await storage.bot_settings.get_maintenance_status(
                current_origin
            )
            local_flag = args[1]
            if local_flag == "off" and len(args) == 2:
                await _set_maintenance(
                    message, storage, config, current_origin, actor, False, None
                )
                return
            if local_flag == "on":
                new_reason = " ".join(args[2:]).strip() or local_reason
                await _set_maintenance(
                    message, storage, config, current_origin, actor, True, new_reason
                )
                return
        await _reply(message, MAINTENANCE_USAGE)

    async def _require_staff_call(call: CallbackQuery):
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
            return None
        return user

    async def _require_root_call(call: CallbackQuery, action_label: str):
        user = await _require_staff_call(call)
        if user is None:
            return None
        if await root(call):
            return user
        now = time.monotonic()
        _drop_expired_security_alerts(now)
        key = (bot_id, user.id, call.data or action_label)
        reserve_audit = key not in _SECURITY_ALERT_THROTTLE
        if reserve_audit:
            _SECURITY_ALERT_THROTTLE[key] = now
        await call.answer("Access Denied", show_alert=True)
        if reserve_audit:
            identity = f"@{html.escape(user.username)}" if user.username else "без username"
            label = html.escape(action_label)
            text = (
                "🚨 <b>Попытка несанкционированного доступа</b>: "
                f"админ {identity} (ID: <code>{user.id}</code>) нажал <b>[{label}]</b>"
            )
            try:
                await send_admin_audit(call.bot, config, text, is_html=True)
            except Exception:
                logger.exception("Не удалось отправить security alert")
        return None

    @router.callback_query(F.data.in_({CB_HOME, CB_BACK}), staff)
    async def handle_home_callback(call: CallbackQuery) -> None:
        user = await _require_staff_call(call)
        if user is None:
            return
        resolved_pending_store.clear(user.id, scope=PendingScope.ADMIN)
        await _show_home_call(call, user.id)
        await call.answer()

    @router.callback_query(F.data == CB_GO_STATS, staff)
    async def handle_stats(call: CallbackQuery) -> None:
        user = await _require_staff_call(call)
        if user is None:
            return
        dash = await _dashboard(
            storage,
            bot_id,
            int(call.bot.id),
        )
        text = _stats_text(dash)
        await panels.edit_or_send(
            call,
            bot_id,
            user.id,
            text,
            back_only_keyboard(),
        )
        await call.answer()

    @router.callback_query(F.data.in_({CB_GO_MAINT, CB_MAINT}), staff)
    async def handle_maint_screen(call: CallbackQuery) -> None:
        user = await _require_staff_call(call)
        if user is None:
            return
        current, reason = await storage.bot_settings.get_maintenance_status(bot_id)
        label = "Снять рубильник" if current else "Опустить рубильник"
        text = "🔴 Рубильник опущен" if current else "🟢 Рубильник снят"
        if current and reason:
            text += "\n" + html.escape(reason)
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=CB_DO_MAINT)],
                *back_only_keyboard(callback_data=CB_HOME).inline_keyboard,
            ]
        )
        await panels.edit_or_send(call, bot_id, user.id, text, markup)
        await call.answer()

    @router.callback_query(F.data == CB_DO_MAINT, staff)
    async def handle_maintenance(call: CallbackQuery) -> None:
        user = await _require_staff_call(call)
        if user is None:
            return
        current, reason = await storage.bot_settings.get_maintenance_status(bot_id)
        turned_on = not current
        await storage.bot_settings.set_maintenance_status(
            bot_id,
            turned_on,
            reason=reason if turned_on else None,
            updated_by=user.id,
        )
        state = "опущен" if turned_on else "снят"
        username = f" @{user.username}" if user.username else ""
        await send_admin_audit(call.bot, config, f"Рубильник {state}. user_id={user.id}{username}")
        report = "Рубильник опущен" if turned_on else "Рубильник снят"
        if turned_on and reason:
            report += ". Причина: " + html.escape(reason)
        await panels.freeze_as_report(call, bot_id, user.id, report)
        await call.answer()
        await _raise_home(call.bot, user.id, await _actor_is_root(user.id), int(call.bot.id))

    @router.callback_query(F.data == CB_GO_BCAST, staff)
    async def handle_broadcast_screen(call: CallbackQuery) -> None:
        user = await _require_root_call(call, "Рассылка")
        if user is None:
            return
        markup = nav_keyboard(
            [InlineKeyboardButton(text="Написать текст", callback_data=CB_BROADCAST)]
        )
        await panels.edit_or_send(
            call,
            bot_id,
            user.id,
            "📢 Рассылка активным пользователям этого бота, 25 сообщений/с.",
            markup,
        )
        await call.answer()

    @router.callback_query(F.data == CB_GO_DB, staff)
    async def handle_db_menu(call: CallbackQuery) -> None:
        user = await _require_root_call(call, "База данных")
        if user is None:
            return
        await panels.edit_or_send(call, bot_id, user.id, DB_MENU_TEXT, db_menu_keyboard())
        await call.answer()

    @router.callback_query(F.data == CB_EXPORT, staff)
    async def handle_export(call: CallbackQuery) -> None:
        user = await _require_root_call(call, "Выгрузка пользователей")
        if user is None:
            return
        await call.answer("Формирую файл...")
        await _send_xlsx_export(call.bot, storage, config, bot_id, user.id)

    @router.callback_query(F.data == CB_DO_BACKUP, staff)
    async def handle_backup_button(call: CallbackQuery) -> None:
        user = await _require_root_call(call, "Бэкап базы данных")
        if user is None:
            return
        await call.answer("Готовлю снимок...")
        await _send_backup(call.bot, storage, user.id, backup_policy=backup_policy)

    register_process_control(
        router,
        bot_id=bot_id,
        config=config,
        staff=staff,
        root=root,
        panels=panels,
        process_control=process_control,
        raise_home=_raise_home,
        require_root_call=_require_root_call,
    )

    if extra_actions is not None:
        @router.callback_query(F.data.startswith("adm_ops:"), staff)
        async def handle_extra_admin_action(call: CallbackQuery) -> None:
            handled = await extra_actions.handle_callback(call)
            if not handled:
                await call.answer()

    @router.callback_query(F.data == CB_FIND, staff)
    async def start_user_lookup(call: CallbackQuery) -> None:
        actor = await _require_staff_call(call)
        if actor is None:
            return
        if is_awaiting_broadcast_text(bot_id, actor.id):
            await call.answer("Сначала завершите рассылку", show_alert=True)
            return
        begin_admin_lookup(bot_id, actor.id, resolved_pending_store)
        await panels.edit_or_send(
            call,
            bot_id,
            actor.id,
            FIND_PROMPT,
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👥 Все пользователи базы", callback_data="adm_users:p:s:0")],
                *back_only_keyboard(callback_data=CB_HOME).inline_keyboard,
            ]),
        )
        await call.answer()

    @router.message(AwaitingAdminLookup(bot_id, resolved_pending_store), F.chat.type == ChatType.PRIVATE, staff)
    async def capture_user_lookup(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        text = (message.text or "").strip()
        command = text.split(maxsplit=1)[0].split("@", 1)[0] if text.startswith("/") else ""
        if command == "/cancel":
            cancel_admin_lookup(bot_id, actor.id, resolved_pending_store)
            await _reply(message, FIND_CANCELLED)
            return
        if not text:
            await message.answer(
                FIND_PROMPT,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="👥 Все пользователи базы",
                                callback_data="adm_users:p:s:0",
                            )
                        ],
                        *back_only_keyboard(callback_data=CB_HOME).inline_keyboard,
                    ]
                ),
            )
            return
        cancel_admin_lookup(bot_id, actor.id, resolved_pending_store)
        target_id = await _target_from_token(message, storage, bot_id, text, USER_NOT_FOUND)
        if target_id is None:
            return
        card = await _dossier(
            storage,
            bot_id,
            target_id,
            extra_user_dossier_lines=extra_user_dossier_lines,
            extra_user_dossier_rows=extra_user_dossier_rows,
            bot_display_name_provider=bot_display_name_provider,
            telegram_bot_id=int(message.bot.id),
            is_root=await _actor_is_root(actor.id),
        )
        if card is None:
            await _reply(message, USER_NOT_FOUND)
            return
        dossier_text, markup = card
        await panels.send_panel(message.bot, bot_id, actor.id, dossier_text, markup)

    @router.message(AwaitingAdminBanReason(resolved_pending_store), F.chat.type == ChatType.PRIVATE, staff)
    async def capture_ban_reason(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        reason = (message.text or "").strip()
        if not reason:
            pending = resolved_pending_store.get(
                actor.id,
                PendingInputKind.ADMIN_BAN_REASON,
                scope=PendingScope.ADMIN,
            )
            hint = "Отправьте в чат причину блокировки:\n(или выберите блокировку без указания причины)"
            if pending is not None and pending.sanction_kind is AdminSanctionKind.SHADOW_BAN:
                hint = "Отправьте в чат причину теневого бана:\n(или выберите блокировку без указания причины)"
            await _reply(message, hint)
            return
        pending = resolved_pending_store.clear(actor.id, scope=PendingScope.ADMIN)
        if (
            pending is None
            or pending.kind is not PendingInputKind.ADMIN_BAN_REASON
            or pending.sanction_kind is None
            or pending.target_user_id is None
        ):
            return
        error = await _apply_named_sanction(
            message,
            pending.sanction_kind,
            pending.target_user_id,
            _clip_reason(reason),
        )
        if error:
            await _reply(message, error)
            return
        card = await _dossier(
            storage,
            bot_id,
            pending.target_user_id,
            extra_user_dossier_lines=extra_user_dossier_lines,
            extra_user_dossier_rows=extra_user_dossier_rows,
            bot_display_name_provider=bot_display_name_provider,
            telegram_bot_id=int(message.bot.id),
            is_root=await _actor_is_root(actor.id),
        )
        if card is None:
            await _reply(message, USER_NOT_FOUND)
            return
        text, markup = card
        await panels.edit_tracked_or_send(message.bot, bot_id, actor.id, text, markup)

    register_broadcast(
        router,
        bot_id,
        storage,
        config,
        staff,
        root=root,
        raise_home=_raise_home,
        require_root_call=_require_root_call,
        pending_store=resolved_pending_store,
    )
    return router


async def _home(
    storage: Storage,
    bot_id: str,
    extra_actions: ExtraAdminActions | None = None,
    *,
    is_root: bool,
    telegram_bot_id: int,
    process_control=None,
) -> tuple[str, InlineKeyboardMarkup]:
    dash = await _dashboard(
        storage,
        bot_id,
        telegram_bot_id,
    )
    lines = [
        "🛠 <b>Админка</b>",
        f"Пользователи: {dash['total']}",
        f"Active (этот бот): {dash['active']}",
        f"Новые сегодня: {dash['new_today']}",
        f"Открытые обращения: {dash['open_tickets']}",
        f"Платежи Stars сегодня: {dash['stars_today']}",
        f"Последний бэкап: {html.escape(dash['last_backup'])}",
        "Рубильник: " + ("🔴 опущен" if dash["maintenance_on"] else "🟢 снят"),
    ]
    if dash["maintenance_on"] and dash["reason"]:
        lines.append(html.escape(str(dash["reason"])))
    extra_rows = (
        extra_actions.home_rows()
        if extra_actions is not None and is_root
        else ()
    )
    return "\n".join(lines), home_keyboard(
        is_root=is_root,
        extra_rows=extra_rows,
        show_restart=process_control is not None,
    )


def _stats_text(dash: dict) -> str:
    return (
        "📊 <b>Статистика</b>\n"
        "\n"
        f"Пользователи: <b>{dash['total']}</b>\n"
        f"Новые сегодня: <b>{dash['new_today']}</b>\n"
        f"Активные за 7 дней: <b>{dash['active_7_days']}</b>\n"
        f"Баны: <b>{dash['sanctioned_total']}</b> "
        f"(из них Shadow: <b>{dash['shadow_banned']}</b>)\n"
        "\n"
        f"Платежи Stars: сегодня <b>{dash['stars_today']} ⭐</b> · "
        f"всего <b>{dash['stars_total']} ⭐</b>\n"
        f"Gift-подписки: <b>{dash['gifts']}</b>\n"
        f"Открытые обращения: <b>{dash['open_tickets']}</b>\n"
        "\n"
        f"Последний бэкап: {dash['last_backup_label']}\n"
        f"Рубильник: {dash['maintenance_label']}"
    )


def _command_args(message: Message) -> list[str]:
    return (message.text or "").split()[1:]


def _parse_user_id(token: str) -> int | None:
    if not token.isdigit():
        return None
    return int(token)


def _parse_users_page_callback(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[:2] != ["adm_users", "p"]:
        return None
    origin, page = parts[2], parts[3]
    if origin not in {"s", "d"} or not page.isascii() or not page.isdigit():
        return None
    return origin, int(page)


def _parse_users_open_callback(data: str) -> int | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[:2] != ["adm_users", "o"] or not parts[2].isascii() or not parts[2].isdigit():
        return None
    return int(parts[2])


async def _users_page_card(storage: Storage, bot_id: str, users, total: int, page: int, total_pages: int, origin: str):
    lines = [f"👥 <b>Пользователи базы</b> (всего: <b>{total}</b>) · Стр. {page + 1}/{total_pages}", ""]
    buttons: list[InlineKeyboardButton] = []
    for local_index, user in enumerate(users):
        badges = []
        if await storage.roles.has_any_role(bot_id, user.user_id, ("superadmin",)):
            badges.append("Суперадмин")
        elif await storage.roles.has_any_role(bot_id, user.user_id, ("admin",)):
            badges.append("Админ")
        if user.is_banned:
            badges.append("Заблокирован")
        if user.is_shadow_banned:
            badges.append("Shadow")
        if await storage.subscriptions.get_active_subscription(bot_id, user.user_id) is not None:
            badges.append("Gift")
        suffix = f" — {' '.join(f'[{badge}]' for badge in badges)}" if badges else ""
        ordinal = page * USERS_PAGE_SIZE + local_index + 1
        identity = f"@{html.escape(user.username)} (<code>{user.user_id}</code>)" if user.username else f"<code>{user.user_id}</code>"
        lines.append(f"{ordinal}. {identity}{suffix}")
        buttons.append(InlineKeyboardButton(text=str(ordinal), callback_data=f"adm_users:o:{user.user_id}"))
    if not users:
        lines.append("Пользователи не найдены.")
    rows = [buttons[index:index + 5] for index in range(0, len(buttons), 5)]
    if total_pages > 1:
        page_buttons = []
        if page > 0:
            page_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_users:p:{origin}:{page - 1}"))
        if page < total_pages - 1:
            page_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"adm_users:p:{origin}:{page + 1}"))
        rows.append(page_buttons)
    back_label = "« Назад в поиск" if origin == "s" else "« Назад в БД"
    back_callback = CB_FIND if origin == "s" else CB_GO_DB
    rows.append([
        InlineKeyboardButton(text=back_label, callback_data=back_callback),
        InlineKeyboardButton(text="В главное меню", callback_data=CB_HOME),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _ban_error(code: str | None) -> str:
    if code == "last_superadmin":
        return LAST_SUPERADMIN
    return USER_NOT_FOUND


def _shadow_error(code: str | None) -> str:
    if code == "target_is_admin":
        return TARGET_IS_ADMIN
    return USER_NOT_FOUND


def _grant_error(code: str | None) -> str:
    if code == "already_granted":
        return ALREADY_GRANTED
    return INVALID_ROLE


def _revoke_error(code: str | None) -> str:
    if code == "last_superadmin":
        return LAST_SUPERADMIN_ROLE
    if code == "not_found":
        return ROLE_NOT_FOUND
    return INVALID_ROLE


def _parse_subscription_entry(data: str) -> int | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[:3] != ["adm_usr", "menu", "subscription"] or not parts[3].isdigit():
        return None
    return int(parts[3])


def _parse_subscription_callback(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "adm_usr" or parts[1] != "sub":
        return None
    if parts[2] not in {"gift30", "giftlife", "token", "revoke"} or not parts[3].isdigit():
        return None
    return parts[2], int(parts[3])


def _clip_reason(reason: str) -> str:
    if len(reason) > 500:
        return reason[:497] + "..."
    return reason


_BAN_REASON_PROMPT = """⚠️ <b>Блокировка пользователя {identity}</b> (ID: <code>{user_id}</code>)

Отправьте в чат причину блокировки:
(или выберите блокировку без указания причины)"""

_SHADOW_REASON_PROMPT = """⚠️ <b>Теневой бан пользователя {identity}</b> (ID: <code>{user_id}</code>)

Отправьте в чат причину теневого бана:
(или выберите блокировку без указания причины)"""


def _sanction_identity(user) -> str:
    if user.username:
        return f"@{html.escape(user.username)}"
    return "без username"


def _sanction_prompt(user, kind: AdminSanctionKind) -> str:
    template = _BAN_REASON_PROMPT if kind is AdminSanctionKind.BAN else _SHADOW_REASON_PROMPT
    return template.format(identity=_sanction_identity(user), user_id=user.user_id)


def _sanction_reason_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡️ Заблокировать без причины",
                    callback_data=f"adm_usr:sanction:no_reason:{user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"adm_usr:sanction:cancel:{user_id}",
                )
            ],
        ]
    )


def _parse_menu_callback(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "adm_usr" or parts[1] != "menu":
        return None
    if parts[2] not in {"sanctions", "dossier"} or not parts[3].isdigit():
        return None
    return parts[2], int(parts[3])


def _parse_sanction_callback(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "adm_usr" or parts[1] != "sanction":
        return None
    if parts[2] not in {"ban", "unban", "shadow_on", "shadow_off", "no_reason", "cancel"} or not parts[3].isdigit():
        return None
    return parts[2], int(parts[3])


async def _invoke_user_port(port, user_id: int):
    if port is None:
        return None
    result = port(user_id)
    if inspect.isawaitable(result):
        result = await result
    return result


def _format_utc_minute(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value)
    try:
        moment = parse_utc(raw)
    except (ValueError, TypeError):
        logger.warning("Неразобранная дата досье: {}", raw)
        return raw
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def _dossier(
    storage: Storage,
    bot_id: str,
    user_id: int,
    extra_user_dossier_lines=None,
    extra_user_dossier_rows=None,
    bot_display_name_provider=None,
    *,
    telegram_bot_id: int,
    is_root: bool = False,
) -> tuple[str, InlineKeyboardMarkup] | None:
    del bot_display_name_provider
    user = await storage.users.get_user(bot_id, user_id)
    if user is None:
        return None
    roles = await _role_names(storage, bot_id, user_id)
    subscription = await storage.subscriptions.get_active_subscription(bot_id, user_id)
    vouchers = await storage.transactions.get_active_vouchers(bot_id, user_id)
    referrals = await storage.referrals.get_referrals_count(bot_id, user_id)
    status_row = await storage.bot_statuses.get_for_user(bot_id, user_id, telegram_bot_id)
    text = _dossier_text(
        user,
        roles,
        subscription,
        len(vouchers),
        referrals,
        lifecycle=None if status_row is None else status_row.status,
        last_seen_at=None if status_row is None else status_row.last_seen_at,
    )
    extra_lines = await _invoke_user_port(extra_user_dossier_lines, user_id)
    if extra_lines:
        text += "\n\n" + "\n".join(extra_lines)
    extra_rows = await _invoke_user_port(extra_user_dossier_rows, user_id)
    return text, _dossier_keyboard(user, extra_rows=extra_rows or (), is_root=is_root)


def _dossier_status(user, lifecycle: str | None) -> str:
    if user.is_banned and user.is_shadow_banned:
        return "🔴 Заблокирован · 👤🕶 Теневой бан"
    if user.is_banned:
        return "🔴 Заблокирован"
    if user.is_shadow_banned:
        return "👤🕶 Теневой бан"
    if lifecycle == "deleted":
        return "⚠️ Аккаунт удалён в Telegram"
    if lifecycle == "stopped":
        return "🛑 Бот остановлен пользователем"
    return "🟢 Активен"


def _identity_line(user) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    username = html.escape(user.username) if user.username else ""
    user_code = f"<code>{user.user_id}</code>"
    if name:
        suffix = f" @{username}" if username else ""
        return f"Имя: <b>{html.escape(name)}</b>{suffix} (ID: {user_code})"
    if username:
        return f"Username: @{username} (ID: {user_code})"
    return f"ID: {user_code}"


def _role_line(roles: list[str]) -> str | None:
    if "superadmin" in roles:
        return "Роль: Суперадминистратор"
    if "admin" in roles:
        return "Роль: Администратор"
    return None


def _subscription_line(subscription) -> str | None:
    if subscription is None:
        return None
    if subscription.is_lifetime or not subscription.expires_at:
        return "Подписка: Gift (бессрочно)"
    day = parse_utc(subscription.expires_at).astimezone(timezone.utc).strftime("%Y-%m-%d")
    return f"Подписка: Gift (до {day})"


def _dossier_text(
    user,
    roles: list[str],
    subscription,
    vouchers: int,
    referrals: int,
    *,
    lifecycle: str | None,
    last_seen_at: str | None,
) -> str:
    lines = [
        "<b>Досье пользователя</b>",
        "",
        _identity_line(user),
        "",
        f"Статус: {_dossier_status(user, lifecycle)}",
    ]
    role = _role_line(roles)
    if role:
        lines.append(role)
    lines.append("")
    visit = _format_utc_minute(user.created_at)
    if visit:
        lines.append(f"Первый визит: {html.escape(visit)}")
    seen = _format_utc_minute(last_seen_at)
    if seen:
        lines.append(f"Последняя активность: {html.escape(seen)}")
    facts: list[str] = []
    subscription_line = _subscription_line(subscription)
    if subscription_line:
        facts.append(subscription_line)
    if vouchers > 0:
        facts.append(f"Токены: {vouchers} шт.")
    if referrals > 0:
        facts.append(f"Рефералы: пригласил {referrals} чел.")
    if facts:
        if lines[-1] != "":
            lines.append("")
        lines.extend(facts)
    return "\n".join(lines)


def _dossier_keyboard(
    user,
    extra_rows: Sequence[Sequence[tuple[str, str]]] = (),
    *,
    is_root: bool = False,
) -> InlineKeyboardMarkup:
    uid = user.user_id
    rows = [
        [
            InlineKeyboardButton(
                text="🔴 Санкции (Бан)",
                callback_data=f"adm_usr:menu:sanctions:{uid}",
            )
        ],
    ]
    if is_root:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎁 Управление подпиской",
                    callback_data=f"adm_usr:menu:subscription:{uid}",
                )
            ]
        )
    for row in extra_rows or ():
        buttons = [
            InlineKeyboardButton(text=text, callback_data=callback_data)
            for text, callback_data in row
        ]
        if buttons:
            rows.append(buttons)
    rows.append(
        [
            InlineKeyboardButton(text="« Назад", callback_data=CB_BACK),
            InlineKeyboardButton(text="В главное меню", callback_data=CB_HOME),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


_SUBSCRIPTION_ACTION_LABELS = {
    "gift30": "🎁 Подарить 30 дней",
    "giftlife": "♾ Подарить бессрочно",
    "token": "🎟 Начислить +1 токен",
    "revoke": "🚫 Отозвать подписку/Gift",
}


def _subscription_keyboard(user_id: int, *, has_subscription: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🎁 Подарить 30 дней",
                callback_data=f"adm_usr:sub:gift30:{user_id}",
            ),
            InlineKeyboardButton(
                text="♾ Подарить бессрочно",
                callback_data=f"adm_usr:sub:giftlife:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎟 Начислить +1 токен",
                callback_data=f"adm_usr:sub:token:{user_id}",
            )
        ],
    ]
    if has_subscription:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🚫 Отозвать подписку/Gift",
                    callback_data=f"adm_usr:sub:revoke:{user_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="« Назад в досье", callback_data=f"adm_usr:menu:dossier:{user_id}"),
            InlineKeyboardButton(text="В главное меню", callback_data=CB_HOME),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sanctions_keyboard(user) -> InlineKeyboardMarkup:
    uid = user.user_id
    if user.is_banned:
        ban_label, ban_action = "🟢 Снять бан", "unban"
    else:
        ban_label, ban_action = "🔴 Выдать бан", "ban"
    if user.is_shadow_banned:
        shadow_label, shadow_action = "👤🕶 Снять теневой бан", "shadow_off"
    else:
        shadow_label, shadow_action = "👤🕶 Включить теневой бан", "shadow_on"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ban_label, callback_data=f"adm_usr:sanction:{ban_action}:{uid}")],
            [InlineKeyboardButton(text=shadow_label, callback_data=f"adm_usr:sanction:{shadow_action}:{uid}")],
            [
                InlineKeyboardButton(text="« Назад в досье", callback_data=f"adm_usr:menu:dossier:{uid}"),
                InlineKeyboardButton(text="В главное меню", callback_data=CB_HOME),
            ],
        ]
    )


async def _apply_sanction(call, storage, config, bot_id: str, action: str, target_id: int) -> str | None:
    actor_id = call.from_user.id
    target = await storage.users.get_user(bot_id, target_id)
    if target is None:
        return USER_NOT_FOUND
    async def _audit(reason: str | None = None) -> None:
        actor = call.from_user
        await send_admin_audit(
            call.bot,
            config,
            format_sanction_audit(
                action,
                target_id=target_id,
                target_username=target.username,
                actor_id=actor.id,
                actor_username=actor.username,
                reason=reason,
            ),
            is_html=True,
        )
    if action == "ban":
        ok, err = await storage.users.set_ban(bot_id, target_id, True, None)
        if not ok:
            return _ban_error(err)
        await _audit()
        return None
    if action == "unban":
        ok, err = await storage.users.set_ban(bot_id, target_id, False)
        if not ok:
            return _ban_error(err)
        await _audit()
        return None
    if action == "shadow_on":
        ok, err = await storage.users.set_shadow_ban(bot_id, target_id, True)
        if not ok:
            return _shadow_error(err)
        await _audit()
        return None
    if action == "shadow_off":
        ok, err = await storage.users.set_shadow_ban(bot_id, target_id, False)
        if not ok:
            return _shadow_error(err)
        await _audit()
        return None
    return None


async def _role_names(storage: Storage, bot_id: str, user_id: int) -> list[str]:
    names: list[str] = []
    if await storage.roles.has_any_role(bot_id, user_id, ("superadmin",)):
        names.append("superadmin")
    if await storage.roles.has_any_role(bot_id, user_id, ("admin",)):
        names.append("admin")
    return names


async def _is_sole_superadmin(storage: Storage, bot_id: str, user_id: int) -> bool:
    if not await storage.roles.has_any_role(bot_id, user_id, ("superadmin",)):
        return False
    return await storage.roles.count_role(bot_id, "superadmin") == 1


def _parse_gift_shape(message: Message) -> tuple[str, int | None] | None:
    args = _command_args(message)
    if not args or len(args) > 2:
        return None
    if len(args) == 1:
        return args[0], None
    if not args[1].isdigit():
        return None
    return args[0], int(args[1])


async def _target_from_token(
    message: Message,
    storage: Storage,
    bot_id: str,
    token: str,
    usage: str,
) -> int | None:
    resolved = await resolve_user_token(storage, bot_id, token)
    if resolved.kind == "invalid":
        await _reply(message, usage)
        return None
    if resolved.kind == "missing":
        await _reply(message, USER_NOT_FOUND)
        return None
    if resolved.kind == "ambiguous":
        await message.answer(format_ambiguous_users(resolved.matches), parse_mode="HTML")
        return None
    return resolved.user_id


async def _actor(message: Message, storage: Storage, bot_id: str):
    user = message.from_user
    if user is None or await _is_banned(storage, bot_id, user.id):
        return None
    return user


async def _reply(message: Message, text: str) -> None:
    await message.answer(html.escape(text), parse_mode="HTML")


async def _send_export(bot, storage: Storage, config: BotChassisConfig, bot_id: str, actor_id: int, scope: str) -> None:
    payload, filename = await build_export(storage, bot_id, scope)
    try:
        await bot.send_document(chat_id=actor_id, document=BufferedInputFile(payload, filename=filename))
    except Exception:
        logger.exception("Не удалось отправить выгрузку")
        try:
            await bot.send_message(actor_id, "Не удалось отправить выгрузку")
        except Exception:
            logger.exception("Не удалось сообщить об ошибке выгрузки")
        return
    await send_admin_audit(bot, config, f"Экспорт {scope}. actor={actor_id}")


async def _send_xlsx_export(bot, storage: Storage, config: BotChassisConfig, bot_id: str, actor_id: int) -> None:
    path = await build_xlsx_export(storage, bot_id)
    try:
        await bot.send_document(
            chat_id=actor_id,
            document=FSInputFile(path, filename=XLSX_FILENAME),
        )
    except Exception:
        logger.exception("Не удалось отправить Excel-книгу")
        try:
            await bot.send_message(actor_id, "Не удалось отправить выгрузку")
        except Exception:
            logger.exception("Не удалось сообщить об ошибке выгрузки")
        return
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    await send_admin_audit(bot, config, f"Экспорт xlsx. actor={actor_id}")


async def _send_backup(bot, storage: Storage, actor_id: int, backup_policy=None) -> None:
    if backup_policy is not None:
        try:
            path = await write_manual_snapshot(storage.engine, backup_policy)
        except Exception:
            logger.exception("Не удалось создать снапшот")
            await _notify(bot, actor_id, "Не удалось отправить снапшот")
            return
        size = os.path.getsize(path)
        limit = backup_policy.transport_limit_bytes
        if size >= limit:
            await _notify(
                bot,
                actor_id,
                f"Снапшот {size} байт не помещается в лимит {limit} байт. Копия оставлена: {path.name}",
            )
            return
        try:
            await bot.send_document(chat_id=actor_id, document=FSInputFile(path, filename="backup.db"))
        except Exception:
            logger.exception("Не удалось отправить снапшот")
            await _notify(
                bot,
                actor_id,
                f"Не удалось отправить снапшот. Копия оставлена: {path.name}",
            )
            return
        try:
            os.unlink(path)
        except OSError:
            logger.exception("Не удалось удалить отправленный ручной снапшот")
        return

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await storage.engine.backup(path)
        if os.path.getsize(path) >= BACKUP_LIMIT_BYTES:
            await _notify(bot, actor_id, BACKUP_TOO_LARGE)
            return
        document = FSInputFile(path, filename="backup.db")
        await bot.send_document(chat_id=actor_id, document=document)
    except Exception:
        logger.exception("Не удалось отправить снапшот")
        await _notify(bot, actor_id, "Не удалось отправить снапшот")
    finally:
        try:
            os.unlink(path)
        except OSError:
            logger.exception("Не удалось удалить временный снапшот")


async def _find_payment(
    storage: Storage,
    bot_id: str,
    target_id: int | None,
    query: str,
    current_telegram_bot_id: int,
):
    def _op(conn):
        row = conn.execute(
            """
            SELECT user_id, payment_id, telegram_payment_charge_id, provider,
                   status, voucher_status, merchant_origin_bot_id,
                   merchant_telegram_bot_id
            FROM transactions
            WHERE bot_id = ?
              AND (? IS NULL OR user_id = ?)
              AND (payment_id = ? OR telegram_payment_charge_id = ?)
            ORDER BY
              CASE WHEN merchant_telegram_bot_id = ? THEN 0 ELSE 1 END,
              CASE provider WHEN 'telegram_stars' THEN 0 ELSE 1 END,
              id DESC
            LIMIT 1
            """,
            (bot_id, target_id, target_id, query, query, current_telegram_bot_id),
        ).fetchone()
        if row is None:
            return None
        return (
            int(row["user_id"]),
            row["payment_id"],
            row["telegram_payment_charge_id"],
            row["provider"],
            row["status"],
            row["voucher_status"],
            row["merchant_origin_bot_id"],
            int(row["merchant_telegram_bot_id"]),
        )

    return await storage.engine.run(_op)


def _maintenance_text(enabled: bool, reason: str | None) -> str:
    text = "Рубильник опущен" if enabled else "Рубильник снят"
    if enabled and reason:
        return f"{text}. Причина: {reason}"
    return text


async def _set_maintenance(message, storage, config, bot_id: str, actor, enabled: bool, reason: str | None) -> None:
    await storage.bot_settings.set_maintenance_status(
        bot_id,
        enabled,
        reason=reason,
        updated_by=actor.id,
    )
    state = "опущен" if enabled else "снят"
    scope = f" ({bot_id})" if bot_id != config.bot_id else ""
    username = f" @{actor.username}" if actor.username else ""
    cause = f" Причина: {reason}." if reason else ""
    await send_admin_audit(
        message.bot,
        config,
        f"Рубильник{scope} {state}.{cause} user_id={actor.id}{username}",
    )
    reply = _maintenance_text(enabled, reason)
    await _reply(message, f"{bot_id}: {reply}" if scope else reply)


def _refund_mark_error(code: str | None) -> str:
    if code == "not_stars":
        return REFUND_NOT_STARS
    if code == "already_refunded":
        return REFUND_ALREADY
    return REFUND_NOT_FOUND


async def _notify(bot, actor_id: int, text: str) -> None:
    try:
        await bot.send_message(actor_id, text)
    except Exception:
        logger.exception("Не удалось отправить сообщение суперадмину")


async def _is_banned(storage: Storage, bot_id: str, user_id: int) -> bool:
    user = await storage.users.get_user(bot_id, user_id)
    return bool(user and user.is_banned)


async def _dashboard(
    storage: Storage,
    bot_id: str,
    telegram_bot_id: int,
) -> dict:
    now_utc = datetime.now(timezone.utc)
    midnight = datetime.now(UTC_PLUS_5).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = midnight.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    active_since = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    last_backup = await storage.scheduled_jobs.latest_done(bot_id, BACKUP_JOB_KEY)
    last_backup_raw = "—"
    if last_backup is not None:
        stamp = last_backup.get("completed_at") or last_backup.get("scheduled_for") or ""
        name = last_backup.get("details") or ""
        last_backup_raw = f"{stamp} {name}".strip() or "—"

    def _op(conn) -> dict:
        users = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN is_banned = 1 OR is_shadow_banned = 1 THEN 1 ELSE 0 END), 0) AS sanctioned_total,
                   COALESCE(SUM(CASE WHEN is_shadow_banned = 1 THEN 1 ELSE 0 END), 0) AS shadow_banned
            FROM users WHERE bot_id = ?
            """,
            (bot_id,),
        ).fetchone()
        gifts = conn.execute(
            """
            SELECT COUNT(*) AS n FROM subscriptions
            WHERE bot_id = ? AND status = 'active'
              AND (is_lifetime = 1 OR expires_at > CURRENT_TIMESTAMP)
            """,
            (bot_id,),
        ).fetchone()
        settings = conn.execute(
            "SELECT is_maintenance, maintenance_reason FROM bot_settings WHERE bot_id = ?",
            (bot_id,),
        ).fetchone()
        active = conn.execute(
            """
            SELECT COUNT(*) AS n FROM user_bot_statuses
            WHERE bot_id = ? AND telegram_bot_id = ? AND status = 'active'
            """,
            (bot_id, telegram_bot_id),
        ).fetchone()
        active_7_days = conn.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS n FROM user_bot_statuses
            WHERE bot_id = ? AND telegram_bot_id = ? AND last_seen_at >= ?
            """,
            (bot_id, telegram_bot_id, active_since),
        ).fetchone()
        new_today = conn.execute(
            """
            SELECT COUNT(*) AS n FROM users
            WHERE bot_id = ? AND created_at >= ?
            """,
            (bot_id, today_start),
        ).fetchone()
        open_tickets = conn.execute(
            """
            SELECT COUNT(*) AS n FROM support_threads
            WHERE bot_id = ? AND message_role = 'header'
              AND ticket_status IN ('open', 'in_progress')
            """,
            (bot_id,),
        ).fetchone()
        stars_today = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS stars
            FROM transactions
            WHERE bot_id = ? AND provider = 'telegram_stars'
              AND currency = 'XTR' AND status = 'paid' AND created_at >= ?
            """,
            (bot_id, today_start),
        ).fetchone()
        stars_total = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS stars
            FROM transactions
            WHERE bot_id = ? AND provider = 'telegram_stars'
              AND currency = 'XTR' AND status = 'paid'
            """,
            (bot_id,),
        ).fetchone()
        maintenance_on = bool(settings["is_maintenance"]) if settings else False
        reason = settings["maintenance_reason"] if settings else None
        return {
            "total": int(users["total"]),
            "sanctioned_total": int(users["sanctioned_total"]),
            "shadow_banned": int(users["shadow_banned"]),
            "gifts": int(gifts["n"]),
            "maintenance_on": maintenance_on,
            "maintenance_label": "🔴 включён" if maintenance_on else "🟢 снят",
            "reason": reason,
            "active": int(active["n"]),
            "active_7_days": int(active_7_days["n"]),
            "new_today": int(new_today["n"]),
            "open_tickets": int(open_tickets["n"]),
            "stars_today": int(stars_today["stars"]),
            "stars_total": int(stars_total["stars"]),
        }

    data = await storage.engine.run(_op)
    data["last_backup"] = last_backup_raw
    data["last_backup_label"] = _format_last_backup(last_backup)
    return data


def _format_last_backup(row: dict | None) -> str:
    if row is None:
        return "нет"
    stamp = row.get("completed_at") or row.get("scheduled_for") or ""
    if not stamp:
        return "нет"
    local = parse_utc(stamp).astimezone(UTC_PLUS_5)
    return local.strftime("%Y-%m-%d %H:%M (UTC+5)")
