"""Смена языка RU/EN. Reply-клавиатура уходит новым сообщением, не через editMessageText."""

from __future__ import annotations

from typing import Optional, Sequence

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardButton

from .keyboards import build_main_menu_keyboard
from .storage import Storage

ALLOWED_LOCALES = frozenset({"ru", "en"})

_SWITCH_OFF = "Смена языка отключена"
_SWITCH_OK = "Язык изменён / Language updated"
_MENU_TEXT = "📱 Главное меню"


def build_language_switch_row() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text="Русский", callback_data="core_lang:ru"),
        InlineKeyboardButton(text="English", callback_data="core_lang:en"),
    ]


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
) -> Router:
    """Замыкает те же domain_rows и тумблеры разделов, что и Button Chassis."""
    localization_router = Router(name="localization_router")

    @localization_router.callback_query(F.data.startswith("core_lang:"))
    async def handle_language_switch(call: CallbackQuery) -> None:
        raw = call.data or ""
        code = raw.split(":", 1)[1] if ":" in raw else ""
        if code not in ALLOWED_LOCALES:
            await call.answer()
            return
        if not enabled:
            await call.answer(_SWITCH_OFF, show_alert=False)
            return
        if call.from_user is None:
            await call.answer()
            return

        saved = await storage.users.set_language_code(bot_id, call.from_user.id, code)
        if locale_cache is not None and saved:
            locale_cache[call.from_user.id] = code
        await call.answer(_SWITCH_OK)

        message = call.message
        if message is None or isinstance(message, InaccessibleMessage):
            return
        await message.answer(
            _MENU_TEXT,
            reply_markup=build_main_menu_keyboard(
                domain_rows=domain_rows,
                locale=code,
                enable_cabinet=enable_cabinet,
                enable_info=enable_info,
                enable_support=enable_support,
            ),
        )

    return localization_router
