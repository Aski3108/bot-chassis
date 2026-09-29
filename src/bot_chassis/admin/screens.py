"""Админские панели: отдельный трекер без DELETE-политики пользовательских карточек."""

from __future__ import annotations

from typing import Sequence

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger

CB_GO_STATS = "adm_go:stats"
CB_GO_MAINT = "adm_go:maint"
CB_DO_MAINT = "adm_do:maint"
CB_GO_BCAST = "adm_go:bcast"
CB_GO_EXPORT = "adm_go:export"
CB_GO_BACKUP = "adm_go:backup"
CB_DO_BACKUP = "adm_do:backup"
CB_GO_RESTART = "adm_go:restart"
CB_BACK = "adm_back"

ROOT_ONLY_CALLBACKS = frozenset(
    {
        CB_GO_BCAST,
        CB_GO_EXPORT,
        CB_GO_BACKUP,
        CB_GO_RESTART,
        "adm_export",
        CB_DO_BACKUP,
        "adm_bcast",
        "adm_bcast:go",
        "adm_bcast:cancel",
        "adm_bcast:stop",
    }
)


class AdminScreenTracker:
    """Одна активная панель на (bot_id, actor_id). Отчёты не удаляет."""

    def __init__(self) -> None:
        self._panels: dict[tuple[str, int], tuple[int, int]] = {}

    def remember(self, bot_id: str, actor_id: int, chat_id: int, message_id: int) -> None:
        self._panels[(bot_id, actor_id)] = (chat_id, message_id)

    def forget(self, bot_id: str, actor_id: int) -> None:
        self._panels.pop((bot_id, actor_id), None)

    def get(self, bot_id: str, actor_id: int) -> tuple[int, int] | None:
        return self._panels.get((bot_id, actor_id))

    async def drop_markup(self, bot, bot_id: str, actor_id: int) -> None:
        entry = self.get(bot_id, actor_id)
        if entry is None:
            return
        chat_id, message_id = entry
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        except Exception:
            logger.debug("Не удалось снять кнопки админ-панели")

    async def retire(self, bot, bot_id: str, actor_id: int) -> None:
        await self.drop_markup(bot, bot_id, actor_id)
        self.forget(bot_id, actor_id)

    async def send_panel(
        self,
        bot,
        bot_id: str,
        actor_id: int,
        text: str,
        markup: InlineKeyboardMarkup,
    ) -> Message:
        await self.retire(bot, bot_id, actor_id)
        sent = await bot.send_message(
            actor_id,
            text,
            reply_markup=markup,
            parse_mode="HTML",
        )
        self.remember(bot_id, actor_id, sent.chat.id, sent.message_id)
        return sent

    async def edit_or_send(
        self,
        call: CallbackQuery,
        bot_id: str,
        actor_id: int,
        text: str,
        markup: InlineKeyboardMarkup,
    ) -> None:
        message = call.message
        if message is None or isinstance(message, InaccessibleMessage):
            await self.send_panel(call.bot, bot_id, actor_id, text, markup)
            return
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            self.remember(bot_id, actor_id, message.chat.id, message.message_id)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                self.remember(bot_id, actor_id, message.chat.id, message.message_id)
                return
            await self.send_panel(call.bot, bot_id, actor_id, text, markup)
        except Exception:
            logger.exception("Не удалось обновить админ-панель")
            await self.send_panel(call.bot, bot_id, actor_id, text, markup)

    async def freeze_as_report(
        self,
        call: CallbackQuery,
        bot_id: str,
        actor_id: int,
        text: str,
    ) -> None:
        message = call.message
        self.forget(bot_id, actor_id)
        if message is None or isinstance(message, InaccessibleMessage):
            try:
                await call.bot.send_message(actor_id, text, parse_mode="HTML")
            except Exception:
                logger.exception("Не удалось отправить отчёт админки")
            return
        try:
            await message.edit_text(text, reply_markup=None, parse_mode="HTML")
        except Exception:
            try:
                await call.bot.send_message(actor_id, text, parse_mode="HTML")
            except Exception:
                logger.exception("Не удалось зафиксировать отчёт админки")


def nav_keyboard(
    *extra_rows: Sequence[InlineKeyboardButton],
) -> InlineKeyboardMarkup:
    rows = [[button for button in row] for row in extra_rows if row]
    rows.append(
        [
            InlineKeyboardButton(text="« Назад", callback_data=CB_BACK),
            InlineKeyboardButton(text="В главное меню", callback_data="adm_home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_keyboard(
    *,
    is_root: bool,
    extra_rows: Sequence[Sequence[tuple[str, str]]] = (),
    show_restart: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data=CB_GO_STATS)],
        [InlineKeyboardButton(text="Найти пользователя", callback_data="adm_find")],
        [InlineKeyboardButton(text="Рубильник", callback_data=CB_GO_MAINT)],
    ]
    if is_root:
        rows.extend(
            [
                [InlineKeyboardButton(text="📢 Рассылка", callback_data=CB_GO_BCAST)],
                [InlineKeyboardButton(text="📥 Выгрузка базы (Excel)", callback_data=CB_GO_EXPORT)],
                [InlineKeyboardButton(text="💾 Бэкап базы данных (.db)", callback_data=CB_GO_BACKUP)],
            ]
        )
        if show_restart:
            rows.append([InlineKeyboardButton(text="🔄 Рестарт", callback_data=CB_GO_RESTART)])
        for row in extra_rows or ():
            buttons = [
                InlineKeyboardButton(text=text, callback_data=callback_data)
                for text, callback_data in row
            ]
            if buttons:
                rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def command_cheatsheet(*, is_root: bool) -> str:
    lines = ["/user", "/ban", "/unban", "/shadowban", "/maintenance", "/refund"]
    if is_root:
        lines.extend(["/grant", "/revoke", "/gift", "/gift_revoke", "/export", "/backup"])
    return "Команды: " + " · ".join(lines)
