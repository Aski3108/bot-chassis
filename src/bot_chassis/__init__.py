"""Пакет шасси кнопочного интерфейса Telegram-бота (Button Chassis / bot_core).

Предоставляет переносимую раму для Telegram-ботов на aiogram v3:
- Постоянная нижняя клавиатура со слотом для доменных кнопок (domain_rows) и тумблерами разделов.
- Системное синее меню команд Telegram (set_my_commands и хук register_button_chassis_startup).
- Команды /menu (неудаляемый носитель клавиатуры), /help и /support.
- Бесшовная смена экранов с политиками CardClosePolicy (DELETE / DROP_MARKUP).
- Дедупликация кликов и отмена устаревших задач (ActiveTaskTracker).
- Хранилище ввода с честным TTL 15 минут (PendingInputStore).
- Двусторонний мост поддержки по композитному ключу (chat_id, message_id) с персистентностью и лимитом тикетов.
- Порты для доменных обработчиков Кабинета и Info с обязательной регистрацией экранов.
"""

from .contracts import (
    BTN_CABINET,
    BTN_INFO,
    BTN_SUPPORT,
    BTN_CABINET_RU,
    BTN_CABINET_EN,
    BTN_INFO_RU,
    BTN_INFO_EN,
    BTN_SUPPORT_RU,
    BTN_SUPPORT_EN,
    ALL_SERVICE_MENU_BUTTONS,
    ALL_MAIN_MENU_BUTTONS,
    is_main_menu_button,
    extract_domain_labels,
    MenuLabels,
    CB_SUPPORT_CANCEL,
    CB_NAV_CLOSE,
)
from .keyboards import (
    build_main_menu_keyboard,
    build_inline_keyboard,
    build_support_prompt_keyboard,
    build_close_inline_keyboard,
)
from .lifecycle import (
    UserScreenTracker,
    CardClosePolicy,
    close_card_screen,
    edit_or_send,
)
from .dispatcher import (
    ActiveTaskTracker,
)
from .followup import (
    PendingInput,
    PendingInputKind,
    PendingInputStore,
)
from .commands import (
    setup_bot_commands,
    register_button_chassis_startup,
)
from .support_bridge import (
    SupportThreadStore,
    send_user_report_to_support,
    deliver_support_reply_to_user,
)
from .router import (
    create_button_chassis_router,
    SupportTicketActiveFilter,
)

# Алиасы для обратной совместимости
create_bot_core_router = create_button_chassis_router
close_screen = close_card_screen

__all__ = [
    "BTN_CABINET",
    "BTN_INFO",
    "BTN_SUPPORT",
    "BTN_CABINET_RU",
    "BTN_CABINET_EN",
    "BTN_INFO_RU",
    "BTN_INFO_EN",
    "BTN_SUPPORT_RU",
    "BTN_SUPPORT_EN",
    "ALL_SERVICE_MENU_BUTTONS",
    "ALL_MAIN_MENU_BUTTONS",
    "is_main_menu_button",
    "extract_domain_labels",
    "MenuLabels",
    "build_main_menu_keyboard",
    "build_inline_keyboard",
    "build_support_prompt_keyboard",
    "build_close_inline_keyboard",
    "UserScreenTracker",
    "CardClosePolicy",
    "close_card_screen",
    "close_screen",
    "edit_or_send",
    "ActiveTaskTracker",
    "PendingInput",
    "PendingInputKind",
    "PendingInputStore",
    "setup_bot_commands",
    "register_button_chassis_startup",
    "SupportThreadStore",
    "send_user_report_to_support",
    "deliver_support_reply_to_user",
    "create_button_chassis_router",
    "create_bot_core_router",
    "SupportTicketActiveFilter",
]
