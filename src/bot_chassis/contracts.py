"""
Контракты и константы пользовательского интерфейса (bot_chassis).
Определяет стабильные названия кнопок, маркеры маршрутизации и валидацию.
"""

from dataclasses import dataclass

# Канонические названия постоянных кнопок главного меню
BTN_CABINET = "👤 Личный кабинет"
BTN_INFO = "ℹ️ Info"
BTN_SUPPORT = "💬 Поддержка"

# Обратная совместимость с альтернативными версиями текста
LEGACY_BTN_CABINET_ALIASES = frozenset({
    "Личный кабинет",
    "Кабинет",
    "💼 Личный кабинет",
    "Мой профиль",
})

LEGACY_BTN_INFO_ALIASES = frozenset({
    "Info",
    "О сервисе",
    "ℹ️ О сервисе",
    "Информация",
    "FAQ",
})

LEGACY_BTN_SUPPORT_ALIASES = frozenset({
    "Поддержка",
    "Служба поддержки",
    "🛟 Поддержка",
    "Report",
    "Помощь",
})

# Полный набор распознаваемых кнопок главного меню для мгновенного сброса фоллоу-апов
ALL_MAIN_MENU_BUTTONS = frozenset({
    BTN_CABINET,
    BTN_INFO,
    BTN_SUPPORT,
    *LEGACY_BTN_CABINET_ALIASES,
    *LEGACY_BTN_INFO_ALIASES,
    *LEGACY_BTN_SUPPORT_ALIASES,
})

# Стабильные префиксы callback_data для инлайн-кнопок
CALLBACK_PREFIX_CABINET = "cabinet:"
CALLBACK_PREFIX_INFO = "info:"
CALLBACK_PREFIX_SUPPORT = "support:"
CALLBACK_PREFIX_NAV = "nav:"

SUPPORTED_CALLBACK_PREFIXES = (
    CALLBACK_PREFIX_CABINET,
    CALLBACK_PREFIX_INFO,
    CALLBACK_PREFIX_SUPPORT,
    CALLBACK_PREFIX_NAV,
)


def is_main_menu_button(text: str | None) -> bool:
    """
    Проверяет, совпадает ли текст сообщения с любой кнопкой главного меню.
    Используется для мгновенного прерывания режима ввода текста (follow-up)
    при нажатии пользователем навигационной кнопки.
    """
    if not text:
        return False
    return text.strip() in ALL_MAIN_MENU_BUTTONS


@dataclass(slots=True, frozen=True)
class CoreMenuLabels:
    cabinet: str = BTN_CABINET
    info: str = BTN_INFO
    support: str = BTN_SUPPORT
