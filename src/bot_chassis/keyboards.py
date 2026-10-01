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

from .contracts import (
    MenuLabels,
    CB_NAV_CLOSE,
    CB_SUPPORT_CANCEL,
    CB_SUPPORT_HUB,
    CB_SUPPORT_TICKET_CLOSE_PREFIX,
    CB_SUPPORT_TICKET_REOPEN_PREFIX,
    CB_SUPPORT_USER_REPLY_PREFIX,
    CB_REVIEW_CONSENT_YES,
    CB_REVIEW_CONSENT_NO,
    CB_REVIEW_PUBLISH_PREFIX,
    CB_REVIEW_REJECT_PREFIX,
)


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
    - Ниже включённые служебные кнопки всегда стоят в одном ряду:
        [👤 Личный кабинет] [ℹ️ Info/FAQ] [💬 Поддержка]
    """
    labels = MenuLabels.for_locale(locale)
    keyboard: list[list[KeyboardButton]] = []

    # 1. Доменный ряд (если передан кузовом)
    if domain_rows:
        for row in domain_rows:
            valid_btns = [KeyboardButton(text=btn_text) for btn_text in row if btn_text]
            if valid_btns:
                keyboard.append(valid_btns)

    # 2. Все включённые служебные кнопки — один ряд
    service_row: list[KeyboardButton] = []
    if enable_cabinet:
        service_row.append(KeyboardButton(text=labels.cabinet))
    if enable_info:
        service_row.append(KeyboardButton(text=labels.info))
    if enable_support:
        service_row.append(KeyboardButton(text=labels.support))
    if service_row:
        keyboard.append(service_row)

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


def build_support_overview_keyboard(
    *,
    show_review: bool = False,
    show_donate: bool = False,
) -> InlineKeyboardMarkup:
    """Обзор поддержки: запрос, опционально отзыв и донат, назад на старт."""
    rows = [[InlineKeyboardButton(text="📝 Написать в поддержку", callback_data="core_sup:request")]]
    if show_review:
        rows.append([InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="core_sup:review")])
    if show_donate:
        rows.append([InlineKeyboardButton(text="💛 Поддержать проект", callback_data="core_sup:donate")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="core_sup:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_support_prompt_keyboard(
    cancel_callback: str = CB_SUPPORT_CANCEL,
    cancel_label: str = "Отмена",
    extra_rows: Sequence[Sequence[tuple[str, str]]] | None = None,
    back_callback: str = CB_SUPPORT_HUB,
    back_label: str = "Назад",
) -> InlineKeyboardMarkup:
    """Карточка ожидания нового обращения: без донатных SKU, только отмена.

    back_callback и back_label остаются в сигнатуре для старых вызовов,
    но на карточке ввода кнопки «Назад» больше нет.
    """
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
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_donation_keyboard(
    items: Sequence[tuple[str, str]],
    back_callback: str = CB_SUPPORT_HUB,
) -> InlineKeyboardMarkup:
    """Каталог донатов. Пустой список не вызывают: кнопку скрывает обзор."""
    rows = [
        [InlineKeyboardButton(text=title, callback_data=callback)]
        for title, callback in items
    ]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_operator_ticket_keyboard(ticket_id: str, *, closed: bool) -> InlineKeyboardMarkup:
    """Кнопки оператора на карточке тикета. Отработанное действие снимается заменой разметки."""
    if closed:
        rows = [[
            InlineKeyboardButton(
                text="↩️ Открыть снова",
                callback_data=f"{CB_SUPPORT_TICKET_REOPEN_PREFIX}{ticket_id}",
            )
        ]]
    else:
        rows = [[
            InlineKeyboardButton(
                text="✅ Закрыть обращение",
                callback_data=f"{CB_SUPPORT_TICKET_CLOSE_PREFIX}{ticket_id}",
            )
        ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_user_ticket_reply_keyboard(ticket_id: str) -> InlineKeyboardMarkup:
    """Пользователь продолжает тот же тикет, лимит новых обращений не проверяется."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Ответить поддержке",
                callback_data=f"{CB_SUPPORT_USER_REPLY_PREFIX}{ticket_id}",
            )
        ]]
    )


def build_review_consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, можно опубликовать", callback_data=CB_REVIEW_CONSENT_YES),
            ],
            [
                InlineKeyboardButton(text="Нет, не публиковать", callback_data=CB_REVIEW_CONSENT_NO),
            ],
        ]
    )


def build_review_moderation_keyboard(review_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Опубликовать",
                callback_data=f"{CB_REVIEW_PUBLISH_PREFIX}{review_id}",
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"{CB_REVIEW_REJECT_PREFIX}{review_id}",
            ),
        ]]
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
