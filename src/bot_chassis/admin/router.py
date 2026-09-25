"""Экран /admin, команды и рассылка."""

from __future__ import annotations

import html
import os
import tempfile
import uuid

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InaccessibleMessage,
    Message,
)
from aiogram.types import BufferedInputFile, FSInputFile
from loguru import logger

from ..config import BotChassisConfig, resolved_origin
from ..storage import Storage
from .audit import send_admin_audit
from .broadcast import register_broadcast
from .export import EXPORT_SCOPES, build_export
from .filters import AdminRoleFilter, SuperadminRoleFilter

CB_MAINT = "adm_maint"
CB_EXPORT = "adm_export"
CB_BROADCAST = "adm_bcast"
CB_HOME = "adm_home"
SUPERADMIN_ONLY = "Только для суперадмина"
BAN_USAGE = "Формат: /ban user_id [причина]"
UNBAN_USAGE = "Формат: /unban user_id"
SHADOW_USAGE = "Формат: /shadowban user_id 0|1"
USER_NOT_FOUND = "Пользователь не найден"
LAST_SUPERADMIN = "Нельзя забанить последнего суперадмина"
TARGET_IS_ADMIN = "Нельзя наложить тень на admin или superadmin"
GRANT_USAGE = "Формат: /grant user_id role"
REVOKE_USAGE = "Формат: /revoke user_id role"
INVALID_ROLE = "Неизвестная роль. Допустимо: admin, superadmin"
ALREADY_GRANTED = "Роль уже выдана"
ROLE_NOT_FOUND = "Роль не найдена"
LAST_SUPERADMIN_ROLE = "Нельзя снять роль последнего суперадмина"
GIFT_USAGE = "Формат: /gift user_id [days]"
GIFT_REVOKE_USAGE = "Формат: /gift_revoke user_id"
GIFT_NOT_FOUND = "Активный подарок не найден"
USER_USAGE = "Формат: /user user_id"
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
MAINTENANCE_USAGE = "Формат: /maintenance [on|off] [причина] или /maintenance bot_id on|off [причина]"


def create_admin_router(bot_id: str, storage: Storage, config: BotChassisConfig) -> Router:
    router = Router(name="admin")
    staff = AdminRoleFilter(bot_id, storage.roles)
    root = SuperadminRoleFilter(bot_id, storage.roles)

    @router.message(Command("admin", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_admin(message: Message) -> None:
        user = message.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            return
        text, markup = await _home(storage, bot_id)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")

    @router.message(Command("ban", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_ban(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        target_id = _parse_user_id(args[0]) if args else None
        if target_id is None:
            await _reply(message, BAN_USAGE)
            return
        reason = " ".join(args[1:]).strip() or None
        if reason and len(reason) > 500:
            reason = reason[:497] + "..."
        ok, err = await storage.users.set_ban(bot_id, target_id, True, reason)
        if not ok:
            await _reply(message, _ban_error(err))
            return
        await send_admin_audit(
            message.bot,
            config,
            f"Бан user_id={target_id}. Причина: {reason or '—'}. actor={actor.id}",
        )
        await _reply(message, f"Пользователь {target_id} забанен")

    @router.message(Command("unban", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_unban(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        target_id = _parse_user_id(args[0]) if args else None
        if target_id is None:
            await _reply(message, UNBAN_USAGE)
            return
        ok, err = await storage.users.set_ban(bot_id, target_id, False)
        if not ok:
            await _reply(message, _ban_error(err))
            return
        await send_admin_audit(message.bot, config, f"Разбан user_id={target_id}. actor={actor.id}")
        await _reply(message, f"Пользователь {target_id} разбанен")

    @router.message(Command("shadowban", ignore_mention=True), F.chat.type == ChatType.PRIVATE, staff)
    async def handle_shadowban(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        args = _command_args(message)
        target_id = _parse_user_id(args[0]) if args else None
        flag = args[1] if len(args) > 1 else ""
        if target_id is None or flag not in {"0", "1"}:
            await _reply(message, SHADOW_USAGE)
            return
        enabled = flag == "1"
        ok, err = await storage.users.set_shadow_ban(bot_id, target_id, enabled)
        if not ok:
            await _reply(message, _shadow_error(err))
            return
        state = "включён" if enabled else "снят"
        await send_admin_audit(
            message.bot,
            config,
            f"Теневой бан {state} user_id={target_id}. actor={actor.id}",
        )
        await _reply(message, f"Теневой бан {state}: {target_id}")

    @router.message(Command("grant", ignore_mention=True), F.chat.type == ChatType.PRIVATE, root)
    async def handle_grant(message: Message) -> None:
        actor = await _actor(message, storage, bot_id)
        if actor is None:
            return
        parsed = _parse_role_args(message)
        if parsed is None:
            await _reply(message, GRANT_USAGE)
            return
        target_id, role = parsed
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
        parsed = _parse_role_args(message)
        if parsed is None:
            await _reply(message, REVOKE_USAGE)
            return
        target_id, role = parsed
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
        parsed = _parse_gift_args(message)
        if parsed is None:
            await _reply(message, GIFT_USAGE)
            return
        target_id, days = parsed
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
        target_id = _parse_user_id(args[0]) if len(args) == 1 else None
        if target_id is None:
            await _reply(message, GIFT_REVOKE_USAGE)
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
        target_id = _parse_user_id(args[0]) if len(args) == 1 else None
        if target_id is None:
            await _reply(message, USER_USAGE)
            return
        card = await _dossier(storage, bot_id, target_id)
        if card is None:
            await _reply(message, USER_NOT_FOUND)
            return
        text, markup = card
        await message.answer(text, reply_markup=markup, parse_mode="HTML")

    @router.callback_query(F.data.startswith("adm_usr:"), staff)
    async def handle_user_action(call: CallbackQuery) -> None:
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
            return
        parsed = _parse_user_callback(call.data or "")
        if parsed is None:
            await call.answer()
            return
        action, target_id = parsed
        if action in {"gift30", "addvouch", "role_adm"} and not await root(call):
            await call.answer(SUPERADMIN_ONLY, show_alert=True)
            return
        if await storage.users.get_user(bot_id, target_id) is None:
            await call.answer(USER_NOT_FOUND, show_alert=True)
            return
        error = await _apply_dossier_action(call, storage, config, bot_id, action, target_id)
        if error:
            await call.answer(error, show_alert=True)
            return
        await _edit_dossier(call, storage, bot_id, target_id)
        await call.answer()

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
        await _send_backup(message.bot, storage, actor.id)

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

    @router.callback_query(F.data == CB_MAINT, staff)
    async def handle_maintenance(call: CallbackQuery) -> None:
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
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
        await _edit_home(call, storage, bot_id)
        await call.answer()

    @router.callback_query(F.data == CB_EXPORT, staff)
    async def handle_export(call: CallbackQuery) -> None:
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
            return
        if not await root(call):
            await call.answer(SUPERADMIN_ONLY, show_alert=True)
            return
        await call.answer("Формирую выгрузку...")
        await _send_export(call.bot, storage, config, bot_id, user.id, "all")

    @router.callback_query(F.data == CB_HOME, staff)
    async def handle_home_callback(call: CallbackQuery) -> None:
        user = call.from_user
        if user is None or await _is_banned(storage, bot_id, user.id):
            await call.answer()
            return
        await _edit_home(call, storage, bot_id)
        await call.answer()

    register_broadcast(router, bot_id, storage, config, staff)
    return router


def _home_keyboard(maintenance_on: bool) -> InlineKeyboardMarkup:
    maint_label = "🔴 Переключить рубильник" if maintenance_on else "🟢 Переключить рубильник"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=maint_label, callback_data=CB_MAINT)],
            [InlineKeyboardButton(text="📥 Выгрузка базы (Excel)", callback_data=CB_EXPORT)],
            [InlineKeyboardButton(text="📢 Новая рассылка", callback_data=CB_BROADCAST)],
        ]
    )


async def _home(storage: Storage, bot_id: str) -> tuple[str, InlineKeyboardMarkup]:
    total, banned, paid_sum, gifts, maintenance_on, reason = await _summary(storage, bot_id)
    lines = [
        "🛠 <b>Админка</b>",
        f"Пользователи: {total}",
        f"Бан: {banned}",
        f"Оплаты: {paid_sum} XTR",
        f"Подарки: {gifts}",
        "Рубильник: " + ("🔴 опущен" if maintenance_on else "🟢 снят"),
    ]
    if maintenance_on and reason:
        lines.append(html.escape(reason))
    return "\n".join(lines), _home_keyboard(maintenance_on)


async def _edit_home(call: CallbackQuery, storage: Storage, bot_id: str) -> None:
    message = call.message
    if message is None or isinstance(message, InaccessibleMessage):
        return
    text, markup = await _home(storage, bot_id)
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось обновить экран /admin")


def _command_args(message: Message) -> list[str]:
    return (message.text or "").split()[1:]


def _parse_user_id(token: str) -> int | None:
    if not token.isdigit():
        return None
    return int(token)


def _ban_error(code: str | None) -> str:
    if code == "last_superadmin":
        return LAST_SUPERADMIN
    return USER_NOT_FOUND


def _shadow_error(code: str | None) -> str:
    if code == "target_is_admin":
        return TARGET_IS_ADMIN
    return USER_NOT_FOUND


def _parse_role_args(message: Message) -> tuple[int, str] | None:
    args = _command_args(message)
    if len(args) != 2:
        return None
    target_id = _parse_user_id(args[0])
    if target_id is None:
        return None
    return target_id, args[1]


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


def _parse_user_callback(data: str) -> tuple[str, int] | None:
    action, _, target = data.removeprefix("adm_usr:").partition(":")
    if action not in {"ban", "shban", "gift30", "addvouch", "role_adm"} or not target.isdigit():
        return None
    return action, int(target)


def _user_callback(action: str, user_id: int) -> str:
    return f"adm_usr:{action}:{user_id}"


async def _dossier(storage: Storage, bot_id: str, user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    user = await storage.users.get_user(bot_id, user_id)
    if user is None:
        return None
    roles = await _role_names(storage, bot_id, user_id)
    subscription = await storage.subscriptions.get_active_subscription(bot_id, user_id)
    vouchers = await storage.transactions.get_active_vouchers(bot_id, user_id)
    payments = await _paid_count(storage, bot_id, user_id)
    referrals = await storage.referrals.get_referrals_count(bot_id, user_id)
    return _dossier_text(user, roles, subscription, len(vouchers), payments, referrals), _dossier_keyboard(
        user, "admin" in roles
    )


def _dossier_text(user, roles: list[str], subscription, vouchers: int, payments: int, referrals: int) -> str:
    username = f"@{html.escape(user.username)}" if user.username else "—"
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    source = html.escape(user.traffic_source) if user.traffic_source else "—"
    vip = "Отсутствует"
    if subscription is not None:
        vip = "Бессрочно" if subscription.is_lifetime else f"до {subscription.expires_at[:10]}"
    lines = [
        f"👤 Досье пользователя: {username} (ID: {user.user_id})",
        f"Имя: {html.escape(name) if name else '—'}",
        f"📅 Первый визит: {html.escape(user.created_at)} UTC",
        f"🌐 Язык: {html.escape(user.language_code)} | Источник / Реф: {source}",
        "🔒 Статус: " + ("Забанен" if user.is_banned else "Активен")
        + " (Теневой бан: " + ("ДА" if user.is_shadow_banned else "НЕТ") + ")",
        "👑 Роли: " + (", ".join(roles) if roles else "нет"),
        f"🎁 VIP Доступ: {vip}",
        f"🎟 Талоны: {vouchers} шт. (Оплат всего: {payments})",
        f"👥 Пригласил рефералов: {referrals}",
    ]
    return "\n".join(lines)


def _dossier_keyboard(user, has_admin: bool) -> InlineKeyboardMarkup:
    ban_label = "🟢 Разбанить" if user.is_banned else "🔴 Забанить"
    shadow_label = "👻 Теневой бан: ВЫКЛ" if user.is_shadow_banned else "👻 Теневой бан: ВКЛ"
    role_label = "🚫 Снять Admin" if has_admin else "👑 Роль Admin"
    uid = user.user_id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ban_label, callback_data=_user_callback("ban", uid))],
            [InlineKeyboardButton(text=shadow_label, callback_data=_user_callback("shban", uid))],
            [InlineKeyboardButton(text="🎁 +30 дней VIP", callback_data=_user_callback("gift30", uid))],
            [InlineKeyboardButton(text="🎟 +1 талон", callback_data=_user_callback("addvouch", uid))],
            [InlineKeyboardButton(text=role_label, callback_data=_user_callback("role_adm", uid))],
            [InlineKeyboardButton(text="« Главное меню админки", callback_data=CB_HOME)],
        ]
    )


async def _apply_dossier_action(call, storage, config, bot_id: str, action: str, target_id: int) -> str | None:
    actor_id = call.from_user.id
    profile = await storage.users.get_user(bot_id, target_id)
    if profile is None:
        return USER_NOT_FOUND
    if action == "ban":
        enabled = not profile.is_banned
        ok, err = await storage.users.set_ban(bot_id, target_id, enabled)
        if not ok:
            return _ban_error(err)
        text = (
            f"Бан user_id={target_id}. Причина: —. actor={actor_id}"
            if enabled
            else f"Разбан user_id={target_id}. actor={actor_id}"
        )
        await send_admin_audit(call.bot, config, text)
        return None
    if action == "shban":
        enabled = not profile.is_shadow_banned
        ok, err = await storage.users.set_shadow_ban(bot_id, target_id, enabled)
        if not ok:
            return _shadow_error(err)
        state = "включён" if enabled else "снят"
        await send_admin_audit(call.bot, config, f"Теневой бан {state} user_id={target_id}. actor={actor_id}")
        return None
    if action == "gift30":
        ok, _err = await storage.subscriptions.grant_gift_access(bot_id, target_id, granted_by=actor_id, days=30)
        if not ok:
            return GIFT_NOT_FOUND
        await send_admin_audit(call.bot, config, f"Подарок выдан user_id={target_id} (30 дн.). actor={actor_id}")
        return None
    if action == "addvouch":
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
    has_admin = await storage.roles.has_any_role(bot_id, target_id, ("admin",))
    if has_admin and await _is_sole_superadmin(storage, bot_id, target_id):
        return LAST_SUPERADMIN_ROLE
    if has_admin:
        ok, err = await storage.roles.revoke_role(bot_id, target_id, "admin")
        if not ok:
            return _revoke_error(err)
        await send_admin_audit(call.bot, config, f"Роль admin снята user_id={target_id}. actor={actor_id}")
        return None
    ok, err = await storage.roles.grant_role(bot_id, target_id, "admin", granted_by=actor_id)
    if not ok:
        return _grant_error(err)
    await send_admin_audit(call.bot, config, f"Роль admin выдана user_id={target_id}. actor={actor_id}")
    return None


async def _edit_dossier(call: CallbackQuery, storage: Storage, bot_id: str, user_id: int) -> None:
    message = call.message
    if message is None or isinstance(message, InaccessibleMessage):
        return
    card = await _dossier(storage, bot_id, user_id)
    if card is None:
        return
    text, markup = card
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось обновить досье /user")


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


async def _paid_count(storage: Storage, bot_id: str, user_id: int) -> int:
    def _op(conn) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM transactions
            WHERE bot_id = ? AND user_id = ? AND status = 'paid'
            """,
            (bot_id, user_id),
        ).fetchone()
        return int(row["n"])

    return await storage.engine.run(_op)


def _parse_gift_args(message: Message) -> tuple[int, int | None] | None:
    args = _command_args(message)
    if not args or len(args) > 2:
        return None
    target_id = _parse_user_id(args[0])
    if target_id is None:
        return None
    if len(args) == 1:
        return target_id, None
    if not args[1].isdigit():
        return None
    return target_id, int(args[1])


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


async def _send_backup(bot, storage: Storage, actor_id: int) -> None:
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


async def _summary(storage: Storage, bot_id: str) -> tuple[int, int, int, int, bool, str | None]:
    def _op(conn) -> tuple[int, int, int, int, bool, str | None]:
        users = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END), 0) AS banned
            FROM users WHERE bot_id = ?
            """,
            (bot_id,),
        ).fetchone()
        paid = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS paid_sum
            FROM transactions WHERE bot_id = ? AND status = 'paid'
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
        maintenance_on = bool(settings["is_maintenance"]) if settings else False
        reason = settings["maintenance_reason"] if settings else None
        return (
            int(users["total"]),
            int(users["banned"]),
            int(paid["paid_sum"]),
            int(gifts["n"]),
            maintenance_on,
            reason,
        )

    return await storage.engine.run(_op)
