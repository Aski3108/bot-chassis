"""Фабрика клавиатур шасси интерфейса (Button Chassis).

Предоставляет:
1. Постоянную нижнюю Reply-клавиатуру с поддержкой:
   - слота доменного ряда (domain_rows) над служебной тройкой;
   - тумблеров включения/отключения разделов (enable_cabinet, enable_info, enable_support);
   - персональной локализации (locale).
2. Универсальные конструкторы Inline-клавиатур без хардкода доменной логики.
"""

from __future__ import annotations
from typing import Sequence, Optional
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from .contracts import MenuLabels, CB_NAV_CLOSE, CB_SUPPORT_CANCEL


def build_main_menu_keyboard(
    domain_rows: Optional[Sequence[Sequence[str]]] = None,
    locale: str = "ru",
    enable_cabinet: bool = True,
    enable_info: bool = True,
    enable_support: bool = True,
    placeholder: str = "Выберите действие в меню",
) -> ReplyKeyboardMarkup:
    """
    Создает нижнюю Reply-клавиатуру:
    - Если переданы domain_rows — они размещаются ВЕРХНИМИ рядами над служебной тройкой.
      (Например, для Chat Listener: [["Ваши чаты", "Ваши слова"]]).
    - Ниже размещаются служебные кнопки (в зависимости от тумблеров):
        [👤 Личный кабинет]
        [ℹ️ Info] [💬 Поддержка]
    """
    labels = MenuLabels.for_locale(locale)
    keyboard: list[list[KeyboardButton]] = []

    # 1. Доменный ряд (если передан кузовом)
    if domain_rows:
        for row in domain_rows:
            valid_btns = [KeyboardButton(text=btn_text) for btn_text in row if btn_text]
            if valid_btns:
                keyboard.append(valid_btns)

    # 2. Служебная тройка с тумблерами
    if enable_cabinet:
        keyboard.append([KeyboardButton(text=labels.cabinet)])

    second_row: list[KeyboardButton] = []
    if enable_info:
        second_row.append(KeyboardButton(text=labels.info))
    if enable_support:
        second_row.append(KeyboardButton(text=labels.support))

    if second_row:
        keyboard.append(second_row)

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder=placeholder,
    )


def build_inline_keyboard(
    rows: Sequence[Sequence[tuple[str, str]]],
) -> InlineKeyboardMarkup:
    """
    Универсальный построитель инлайн-клавиатуры из списка строк.
    Каждый элемент — кортеж: (текст_кнопки, callback_data_или_url).
    """
    inline_keyboard = []
    for row in rows:
        button_row = []
        for text, data_or_url in row:
            if data_or_url.startswith(("http://", "https://", "tg://")):
                button_row.append(InlineKeyboardButton(text=text, url=data_or_url))
            else:
                button_row.append(InlineKeyboardButton(text=text, callback_data=data_or_url))
        inline_keyboard.append(button_row)
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def build_support_prompt_keyboard(
    cancel_callback: str = CB_SUPPORT_CANCEL,
    cancel_label: str = "🔙 Отмена",
    extra_rows: Sequence[Sequence[tuple[str, str]]] | None = None,
) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура экрана ожидания ввода тикета поддержки (кнопка отмены)."""
    rows = [
        [
            InlineKeyboardButton(text=text, url=value)
            if value.startswith(("http://", "https://", "tg://"))
            else InlineKeyboardButton(text=text, callback_data=value)
            for text, value in row
        ]
        for row in (extra_rows or ())
        if row
    ]
    rows.append([InlineKeyboardButton(text=cancel_label, callback_data=cancel_callback)])
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def build_close_inline_keyboard(
    close_callback: str = CB_NAV_CLOSE,
    close_label: str = "✖️ Закрыть",
) -> InlineKeyboardMarkup:
    """Инлайн-кнопка закрытия сервисного сообщения."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=close_label, callback_data=close_callback)]
        ]
    )
