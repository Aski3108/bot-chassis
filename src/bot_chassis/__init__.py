"""
Пакет универсального переносимого костяка Telegram-бота (bot_chassis).
Предоставляет готовый каркас интерфейса, навигации, меню, личного кабинета
и двустороннего моста технической поддержки.
"""

from .contracts import (
    BTN_CABINET,
    BTN_INFO,
    BTN_SUPPORT,
    ALL_MAIN_MENU_BUTTONS,
    is_main_menu_button,
)
from .keyboards import (
    build_main_menu_keyboard,
    build_cabinet_inline_keyboard,
    build_info_inline_keyboard,
    build_support_inline_keyboard,
    build_back_reply_keyboard,
    build_inline_keyboard,
)
from .lifecycle import (
    edit_or_send,
    close_screen,
    close_previous_user_screen,
    remember_user_screen,
    get_user_last_screen,
    forget_user_screen,
)
from .dispatcher import (
    ActiveTaskTracker,
    get_task_tracker,
)
from .followup import (
    PendingInput,
    PendingInputKind,
    InMemoryPendingInputStore,
    get_pending_input_store,
)
from .commands import (
    setup_bot_commands,
    notify_admins_on_startup,
)
from .support_bridge import (
    send_user_report_to_support,
    deliver_support_reply_to_user,
    register_support_thread,
    resolve_user_by_admin_reply,
)
from .router import create_bot_chassis_router

__all__ = [
    "BTN_CABINET",
    "BTN_INFO",
    "BTN_SUPPORT",
    "ALL_MAIN_MENU_BUTTONS",
    "is_main_menu_button",
    "build_main_menu_keyboard",
    "build_cabinet_inline_keyboard",
    "build_info_inline_keyboard",
    "build_support_inline_keyboard",
    "build_back_reply_keyboard",
    "build_inline_keyboard",
    "edit_or_send",
    "close_screen",
    "close_previous_user_screen",
    "remember_user_screen",
    "get_user_last_screen",
    "forget_user_screen",
    "ActiveTaskTracker",
    "get_task_tracker",
    "PendingInput",
    "PendingInputKind",
    "InMemoryPendingInputStore",
    "get_pending_input_store",
    "setup_bot_commands",
    "notify_admins_on_startup",
    "send_user_report_to_support",
    "deliver_support_reply_to_user",
    "register_support_thread",
    "resolve_user_by_admin_reply",
    "create_bot_chassis_router",
]
