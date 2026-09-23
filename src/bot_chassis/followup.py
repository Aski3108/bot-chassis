"""
Хранилище временных состояний ожидания ввода (bot_chassis.followup).
Позволяет обрабатывать многошаговые сценарии (например, отправку сообщения в техподдержку)
без громоздких FSM-машин и с гарантированным сбросом при клике на кнопки меню.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict
import time


class PendingInputKind(str, Enum):
    """Типы ожидаемого пользовательского ввода."""
    SUPPORT_MESSAGE = "support_message"    # Пользователь пишет обращение в поддержку
    SUPPORT_REPLY = "support_reply"        # Администратор отвечает конкретному пользователю
    CUSTOM_INPUT = "custom_input"          # Расширяемый тип для доменных сценариев


@dataclass(slots=True, frozen=True)
class PendingInput:
    """Запись об ожидаемом вводе для конкретного пользователя."""
    kind: PendingInputKind
    target_user_id: Optional[int] = None       # ID пользователя-адресата (для ответа админа)
    origin_chat_id: Optional[int] = None
    origin_message_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class InMemoryPendingInputStore:
    """Потокобезопасное in-memory хранилище состояний ввода."""
    _items: Dict[int, PendingInput] = field(default_factory=dict)

    def get(self, user_id: int) -> Optional[PendingInput]:
        """Возвращает текущий режим ввода для пользователя или None."""
        return self._items.get(user_id)

    def set(self, user_id: int, pending_input: PendingInput) -> None:
        """Устанавливает режим ожидания ввода."""
        self._items[user_id] = pending_input

    def clear(self, user_id: int) -> Optional[PendingInput]:
        """Очищает режим ожидания ввода и возвращает удаленное значение."""
        return self._items.pop(user_id, None)

    def is_active(self, user_id: int, kind: Optional[PendingInputKind] = None) -> bool:
        """Проверяет активность режима ввода (опционально конкретного типа)."""
        item = self._items.get(user_id)
        if not item:
            return False
        if kind is not None and item.kind != kind:
            return False
        return True


# Глобальный синглтон хранилища в рамках процесса бота
_SHARED_STORE = InMemoryPendingInputStore()


def get_pending_input_store() -> InMemoryPendingInputStore:
    """Возвращает общий синглтон хранилища состояний ввода."""
    return _SHARED_STORE
