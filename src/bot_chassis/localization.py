"""Один переключатель RU/EN. Reply-клавиатура обновляется только если подписи изменились."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Sequence

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from loguru import logger

from .keyboards import build_main_menu_keyboard
from .contracts import MenuLabels
from .storage import Storage

ALLOWED_LOCALES = frozenset({"ru", "en"})
DEFAULT_RU_LANGUAGE_CODES = frozenset({
    "ru", "be", "uk", "kk", "ky", "uz", "tg", "tk", "hy", "az", "ka", "pl",
})

_SWITCH_OFF = "Смена языка отключена"
_SWITCH_OK = "Язык изменён / Language updated"
_KEYBOARD_CARRIER = "Главное меню"


@dataclass(frozen=True, slots=True)
class InitialLocalePolicy:
    """Какие базовые коды Telegram запускают русский интерфейс."""

    ru_language_codes: frozenset[str] = DEFAULT_RU_LANGUAGE_CODES
    fallback_locale: str = "en"


@dataclass(frozen=True, slots=True)
class MarkupContext:
    locale: str
    user_id: int | None = None


@dataclass(frozen=True, slots=True)
class ChassisScreen:
    """Карточка, которую рама отправляет сама и может дополнить переключателем."""

    text: str
    markup: InlineKeyboardMarkup | None = None
    parse_mode: str | None = "HTML"


@dataclass(frozen=True, slots=True)
class LocaleChangedContext:
    user_id: int
    locale: str
    event: CallbackQuery


def base_language_code(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip().replace("_", "-")
    if not text:
        return None
    return text.split("-", 1)[0].lower()


def resolve_initial_locale(
    raw: str | None,
    policy: InitialLocalePolicy | None = None,
) -> str:
    active = policy or InitialLocalePolicy()
    base = base_language_code(raw)
    if base and base in active.ru_language_codes:
        return "ru"
    return active.fallback_locale


def language_toggle_label(locale: str) -> str:
    if locale == "en":
        return "🌐 Русский / English"
    return "🌐 English / Русский"


def build_language_switch_row(locale: str = "ru") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=language_toggle_label(locale),
            callback_data="core_lang:toggle",
        )
    ]


def decorate_info_markup(markup, context) -> InlineKeyboardMarkup:
    """Один языковой ряд. Уже стоящую кнопку core_lang заменяет, а не дублирует."""
    locale = getattr(context, "locale", None) or "ru"
    button = build_language_switch_row(locale)[0]
    rows: list[list[InlineKeyboardButton]] = []
    if markup is not None:
        for row in markup.inline_keyboard:
            if any((button.callback_data or "").startswith("core_lang:") for button in row):
                continue
            rows.append(list(row))
    rows.append([button])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def visible_service_labels(
    locale: str,
    *,
    enable_cabinet: bool = True,
    enable_info: bool = True,
    enable_support: bool = True,
) -> tuple[str, ...]:
    labels = MenuLabels.for_locale(locale)
    texts: list[str] = []
    if enable_cabinet:
        texts.append(labels.cabinet)
    if enable_info:
        texts.append(labels.info)
    if enable_support:
        texts.append(labels.support)
    return tuple(texts)


def _relabel_toggle(markup: InlineKeyboardMarkup | None, locale: str) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    found = False
    rows: list[list[InlineKeyboardButton]] = []
    label = language_toggle_label(locale)
    for row in markup.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            if (button.callback_data or "").startswith("core_lang:"):
                found = True
                new_row.append(
                    InlineKeyboardButton(text=label, callback_data="core_lang:toggle")
                )
            else:
                new_row.append(button)
        rows.append(new_row)
    if not found:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_localization_router(
    bot_id: str,
    storage: Storage,
    *,
    enabled: bool = False,
    locale_cache: dict[int, str] | None = None,
    domain_rows: Optional[Sequence[Sequence[str]]] = None,
    enable_cabinet: bool = True,
    enable_info: bool = True,
    enable_support: bool = True,
    on_locale_changed: Callable[[LocaleChangedContext], Awaitable[None]] | None = None,
) -> Router:
    """Замыкает те же domain_rows и тумблеры разделов, что и Button Chassis."""
    localization_router = Router(name="localization_router")

    @localization_router.callback_query(F.data.startswith("core_lang:"))
    async def handle_language_switch(call: CallbackQuery) -> None:
        raw = call.data or ""
        code = raw.split(":", 1)[1] if ":" in raw else ""
        if not enabled:
            await call.answer(_SWITCH_OFF, show_alert=False)
            return
        if call.from_user is None:
            await call.answer()
            return
        user_id = call.from_user.id
        current = locale_cache.get(user_id) if locale_cache is not None else None
        if current is None:
            stored = await storage.users.get_user(bot_id, user_id)
            current = stored.language_code if stored is not None else "ru"
        if code == "toggle":
            code = "ru" if current == "en" else "en"
        if code not in ALLOWED_LOCALES:
            await call.answer()
            return

        saved = await storage.users.set_manual_locale(bot_id, user_id, code)
        if locale_cache is not None and saved:
            locale_cache[user_id] = code
        await call.answer(_SWITCH_OK)
        if not saved:
            return

        message = call.message
        if message is not None and not isinstance(message, InaccessibleMessage):
            updated = _relabel_toggle(message.reply_markup, code)
            if updated is not None:
                try:
                    await message.edit_reply_markup(reply_markup=updated)
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        logger.warning(f"Не удалось обновить языковую кнопку: {exc}")

        previous = visible_service_labels(
            current,
            enable_cabinet=enable_cabinet,
            enable_info=enable_info,
            enable_support=enable_support,
        )
        nxt = visible_service_labels(
            code,
            enable_cabinet=enable_cabinet,
            enable_info=enable_info,
            enable_support=enable_support,
        )
        if previous != nxt and call.bot is not None and message is not None and message.chat is not None:
            await call.bot.send_message(
                message.chat.id,
                _KEYBOARD_CARRIER,
                reply_markup=build_main_menu_keyboard(
                    domain_rows=domain_rows,
                    locale=code,
                    enable_cabinet=enable_cabinet,
                    enable_info=enable_info,
                    enable_support=enable_support,
                ),
            )

        if on_locale_changed is not None:
            await on_locale_changed(
                LocaleChangedContext(user_id=user_id, locale=code, event=call)
            )

    return localization_router
