"""Хранилище временных состояний ожидания ввода (Button Chassis).

Позволяет безопасно обрабатывать пользовательский ввод (тикеты поддержки,
текстовые ответы) с гарантированным TTL (по умолчанию 15 минут) и мгновенным
сбросом при нажатии любой навигационной кнопки меню.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PendingInputKind(str, Enum):
    """Типы ожидаемого пользовательского ввода."""
    SUPPORT_MESSAGE = "support_message"    # Пользователь пишет обращение в поддержку
    CUSTOM_INPUT = "custom_input"          # Расширяемый тип для доменных сценариев


@dataclass(slots=True, frozen=True)
class PendingInput:
    """Запись об ожидаемом вводе для конкретного пользователя."""
    kind: PendingInputKind
    target_user_id: Optional[int] = None
    origin_chat_id: Optional[int] = None
    origin_message_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)


class PendingInputStore:
    """
    Экземпляр хранилища состояний ожидания ввода с поддержкой срока жизни (TTL).
    Живёт строго в RAM конкретного экземпляра бота (0 байт на диске).
    """
    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[int, PendingInput] = {}

    def _is_expired(self, item: PendingInput) -> bool:
        return (time.time() - item.created_at) > self.ttl_seconds

    def get(self, user_id: int) -> Optional[PendingInput]:
        """Возвращает текущую запись ввода, если она не истекла по TTL."""
        item = self._items.get(user_id)
        if not item:
            return None
        if self._is_expired(item):
            self._items.pop(user_id, None)
            return None
        return item

    def set(self, user_id: int, pending_input: PendingInput) -> None:
        """Устанавливает режим ожидания ввода."""
        self._items[user_id] = pending_input

    def clear(self, user_id: int) -> Optional[PendingInput]:
        """Очищает режим ожидания ввода и возвращает удалённое значение."""
        return self._items.pop(user_id, None)

    def is_active(self, user_id: int, kind: Optional[PendingInputKind] = None) -> bool:
        """Проверяет активность режима ввода с учётом TTL."""
        item = self.get(user_id)
        if not item:
            return False
        if kind is not None and item.kind != kind:
            return False
        return True

    def purge_expired(self) -> int:
        """Периодическая очистка протухших записей. Возвращает количество удалённых."""
        now = time.time()
        expired_keys = [uid for uid, item in self._items.items() if (now - item.created_at) > self.ttl_seconds]
        for uid in expired_keys:
            self._items.pop(uid, None)
        return len(expired_keys)
