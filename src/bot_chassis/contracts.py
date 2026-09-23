"""Контракты и константы шасси кнопочного интерфейса (Button Chassis).

Определяет названия кнопок главного меню на разных языках,
алиасы для мгновенного сброса ожидания ввода, стабильные callback-префиксы
и предикаты распознавания кнопок (включая доменные ряды).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

# Русские названия кнопок (по умолчанию)
BTN_CABINET_RU: str = "👤 Личный кабинет"
BTN_INFO_RU: str = "ℹ️ Info"
BTN_SUPPORT_RU: str = "💬 Поддержка"

# Английские названия кнопок
BTN_CABINET_EN: str = "👤 Account"
BTN_INFO_EN: str = "ℹ️ Info"
BTN_SUPPORT_EN: str = "💬 Support"

# Канонические дефолты
BTN_CABINET: str = BTN_CABINET_RU
BTN_INFO: str = BTN_INFO_RU
BTN_SUPPORT: str = BTN_SUPPORT_RU

# Алиасы для распознавания кликов и сброса ввода
LEGACY_BTN_CABINET_ALIASES = frozenset({
    "Личный кабинет",
    "Кабинет",
    "💼 Личный кабинет",
    "Мой профиль",
    BTN_CABINET_RU,
    BTN_CABINET_EN,
    "Account",
    "Profile",
})

LEGACY_BTN_INFO_ALIASES = frozenset({
    "Info",
    "О сервисе",
    "ℹ️ О сервисе",
    "Информация",
    "FAQ",
    BTN_INFO_RU,
    BTN_INFO_EN,
})

LEGACY_BTN_SUPPORT_ALIASES = frozenset({
    "Поддержка",
    "Служба поддержки",
    "🛟 Поддержка",
    "Report",
    "Помощь",
    "Support",
    BTN_SUPPORT_RU,
    BTN_SUPPORT_EN,
})

ALL_SERVICE_MENU_BUTTONS: frozenset[str] = frozenset({
    BTN_CABINET,
    BTN_INFO,
    BTN_SUPPORT,
    *LEGACY_BTN_CABINET_ALIASES,
    *LEGACY_BTN_INFO_ALIASES,
    *LEGACY_BTN_SUPPORT_ALIASES,
})

# Алиас для обратной совместимости
ALL_MAIN_MENU_BUTTONS = ALL_SERVICE_MENU_BUTTONS

# Стабильные префиксы callback_data
CALLBACK_PREFIX_CABINET: str = "core_cab:"
CALLBACK_PREFIX_INFO: str = "core_info:"
CALLBACK_PREFIX_SUPPORT: str = "core_sup:"
CALLBACK_PREFIX_NAV: str = "core_nav:"

CB_SUPPORT_CANCEL: str = f"{CALLBACK_PREFIX_SUPPORT}cancel"
CB_NAV_CLOSE: str = f"{CALLBACK_PREFIX_NAV}close"


def extract_domain_labels(domain_rows: Optional[Sequence[Sequence[str]]]) -> frozenset[str]:
    """Извлекает набор строковых подписей из доменных рядов кнопок."""
    if not domain_rows:
        return frozenset()
    labels = set()
    for row in domain_rows:
        for btn in row:
            if btn and isinstance(btn, str):
                labels.add(btn.strip())
    return frozenset(labels)


def is_main_menu_button(
    text: str | None,
    domain_labels: Optional[frozenset[str]] = None,
) -> bool:
    """
    Проверяет, является ли текст сообщения кликом по любой кнопке меню
    (служебной тройке либо доменным кнопкам проекта).
    """
    if not text:
        return False
    clean = text.strip()
    if clean in ALL_SERVICE_MENU_BUTTONS:
        return True
    if domain_labels and clean in domain_labels:
        return True
    return False


@dataclass(slots=True, frozen=True)
class MenuLabels:
    """Контейнер локализованных подписей служебной тройки кнопок."""
    cabinet: str
    info: str
    support: str

    @classmethod
    def for_locale(cls, locale: str = "ru") -> MenuLabels:
        if locale == "en":
            return cls(cabinet=BTN_CABINET_EN, info=BTN_INFO_EN, support=BTN_SUPPORT_EN)
        return cls(cabinet=BTN_CABINET_RU, info=BTN_INFO_RU, support=BTN_SUPPORT_RU)
