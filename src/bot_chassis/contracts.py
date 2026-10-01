"""Контракты и константы шасси кнопочного интерфейса (Button Chassis).

Определяет названия кнопок главного меню на разных языках,
алиасы для мгновенного сброса ожидания ввода, стабильные callback-префиксы
и предикаты распознавания кнопок (включая доменные ряды).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

# Русские названия кнопок (по умолчанию)
BTN_CABINET_RU: str = "👤 Аккаунт"
BTN_INFO_RU: str = "ℹ️ Инфо/FAQ"
BTN_SUPPORT_RU: str = "Поддержка"

# Английские названия кнопок
BTN_CABINET_EN: str = "👤 Account"
BTN_INFO_EN: str = "ℹ️ Info/FAQ"
BTN_SUPPORT_EN: str = "💬 Support"

# Канонические дефолты
BTN_CABINET: str = BTN_CABINET_RU
BTN_INFO: str = BTN_INFO_RU
BTN_SUPPORT: str = BTN_SUPPORT_RU

# Алиасы для распознавания кликов и сброса ввода
LEGACY_BTN_CABINET_ALIASES = frozenset({
    "Личный кабинет",
    "👤 Личный кабинет",
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
    "ℹ️ Info",
    "ℹ️ Info / FAQ ❓",
    "ℹ️ Info/FAQ",
    "Инфо/FAQ",
    "Информация",
    "FAQ",
    BTN_INFO_RU,
    BTN_INFO_EN,
})

LEGACY_BTN_SUPPORT_ALIASES = frozenset({
    "Поддержка",
    "💬 Поддержка",
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
CB_SUPPORT_REQUEST: str = f"{CALLBACK_PREFIX_SUPPORT}request"
CB_SUPPORT_DONATE: str = f"{CALLBACK_PREFIX_SUPPORT}donate"
CB_SUPPORT_REVIEW: str = f"{CALLBACK_PREFIX_SUPPORT}review"
CB_SUPPORT_BACK: str = f"{CALLBACK_PREFIX_SUPPORT}back"
CB_SUPPORT_HUB: str = f"{CALLBACK_PREFIX_SUPPORT}hub"
CB_SUPPORT_TICKET_CLOSE_PREFIX: str = f"{CALLBACK_PREFIX_SUPPORT}tclose:"
CB_SUPPORT_TICKET_REOPEN_PREFIX: str = f"{CALLBACK_PREFIX_SUPPORT}treopen:"
CB_SUPPORT_USER_REPLY_PREFIX: str = f"{CALLBACK_PREFIX_SUPPORT}ureply:"
CALLBACK_PREFIX_REVIEW: str = "core_rev:"
CB_REVIEW_CONSENT_YES: str = f"{CALLBACK_PREFIX_REVIEW}yes"
CB_REVIEW_CONSENT_NO: str = f"{CALLBACK_PREFIX_REVIEW}no"
CB_REVIEW_PUBLISH_PREFIX: str = f"{CALLBACK_PREFIX_REVIEW}pub:"
CB_REVIEW_REJECT_PREFIX: str = f"{CALLBACK_PREFIX_REVIEW}rej:"
CB_NAV_CLOSE: str = f"{CALLBACK_PREFIX_NAV}close"
CB_NAV_CANCEL: str = f"{CALLBACK_PREFIX_NAV}cancel"
LABEL_CANCEL_RU: str = "Отмена"
LABEL_CANCEL_EN: str = "Cancel"
LABEL_BACK_RU: str = "Назад"
LABEL_BACK_EN: str = "Back"
# CB_SUPPORT_BACK / CB_SUPPORT_CANCEL — совместимость: обрабатываются тем же
# хэндлером, что CB_NAV_CANCEL / CB_SUPPORT_HUB.


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
