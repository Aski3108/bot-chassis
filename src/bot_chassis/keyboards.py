"""
Фабрика клавиатур для Telegram-бота на базе aiogram v3 (bot_chassis).
Реализует постоянную нижнюю Reply-клавиатуру (3 кнопки) и конструктор Inline-меню.
"""

from typing import List, Tuple, Optional
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from .contracts import BTN_CABINET, BTN_INFO, BTN_SUPPORT


def build_main_menu_keyboard(
    placeholder: str = "Выберите действие в меню",
) -> ReplyKeyboardMarkup:
    """
    Создает каноническую нижнюю Reply-клавиатуру из 3 кнопок:
      [👤 Личный кабинет]
      [ℹ️ Info] | [💬 Поддержка]

    Ключевые параметры Telegram Bot API:
    - is_persistent=True: клавиатура не сворачивается при вводе текста пользователем.
    - resize_keyboard=True: кнопки компактно подгоняются по высоте.
    - one_time_keyboard=False: клавиатура остается постоянной.
    - input_field_placeholder: подсказка в строке ввода.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CABINET)],
            [KeyboardButton(text=BTN_INFO), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder=placeholder,
    )


def build_back_reply_keyboard(
    button_text: str = "🔙 Главное меню",
) -> ReplyKeyboardMarkup:
    """Вспомогательная Reply-клавиатура возврата в главное меню."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=button_text)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def build_inline_keyboard(
    rows: List[List[Tuple[str, str]]],
) -> InlineKeyboardMarkup:
    """
    Универсальный построитель инлайн-клавиатуры из списка строк.
    Каждый элемент — кортеж: (текст_кнопки, callback_data_или_url).
    Если значение начинается с 'http://' или 'https://' или 'tg://' — создается url-кнопка,
    иначе — callback_data.
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


def build_cabinet_inline_keyboard(
    has_reports: bool = False,
    last_report_id: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """Инлайн-кнопки Личного кабинета."""
    rows = []
    if has_reports and last_report_id:
        rows.append([("📥 Скачать последний отчёт (PDF)", f"cabinet:download:{last_report_id}")])
        rows.append([("📜 Архив отчётов", "cabinet:archive:page:1")])
    rows.append([("⭐ Пополнить баланс Stars", "cabinet:buy_stars")])
    return build_inline_keyboard(rows)


def build_info_inline_keyboard(
    locale: str = "ru",
    show_projects_link: bool = True,
) -> InlineKeyboardMarkup:
    """Инлайн-кнопки раздела Info (научный хаб, язык, проекты)."""
    next_lang_label = "🌐 English" if locale == "ru" else "🌐 Русский"
    next_lang_code = "en" if locale == "ru" else "ru"
    
    rows = [
        [
            (next_lang_label, f"info:lang:{next_lang_code}"),
            ("🚀 Другие проекты", "info:projects") if show_projects_link else None,
        ],
        [("📖 Научная методология", "info:methodology")],
        [("📲 Инструкция по экспорту", "info:export_guide")],
        [("⚖️ Конфиденциальность (152-ФЗ)", "info:privacy")],
    ]
    # Фильтруем пустые элементы
    cleaned_rows = [[btn for btn in row if btn is not None] for row in rows]
    return build_inline_keyboard(cleaned_rows)


def build_support_inline_keyboard(
    support_chat_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """Инлайн-кнопки раздела Поддержки."""
    rows = []
    if support_chat_url:
        rows.append([("👥 Чат комьюнити", support_chat_url)])
    rows.append([("⭐ Поддержать проект (Stars)", "support:donate_stars")])
    rows.append([("🔙 Закрыть", "nav:close")])
    return build_inline_keyboard(rows)
