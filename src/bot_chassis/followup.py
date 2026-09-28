"""Хранилище временных состояний ожидания ввода (Button Chassis).

Ожидания разделены по scopes: пользовательская навигация не стирает
админский поиск, рассылку и доменный ввод кузова.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PendingScope(str, Enum):
    """Контуры ожидания ввода. Старый вызов без scope работает как USER."""

    USER = "user_navigation"
    ADMIN = "admin_navigation"
    BROADCAST = "broadcast"
    DOMAIN = "domain"


class PendingInputKind(str, Enum):
    """Типы ожидаемого пользовательского ввода."""
    SUPPORT_MESSAGE = "support_message"
    SUPPORT_REPLY = "support_reply"
    REVIEW = "review"
    REVIEW_CONSENT = "review_consent"
    CUSTOM_INPUT = "custom_input"
    ADMIN_LOOKUP = "admin_lookup"


@dataclass(slots=True, frozen=True)
class PendingInput:
    """Запись об ожидаемом вводе для конкретного пользователя."""
    kind: PendingInputKind
    target_user_id: Optional[int] = None
    origin_chat_id: Optional[int] = None
    origin_message_id: Optional[int] = None
    ticket_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class PendingInputStore:
    """
    Экземпляр хранилища состояний ожидания ввода с поддержкой срока жизни (TTL).
    Живёт строго в RAM конкретного экземпляра бота (0 байт на диске).
    """
    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[tuple[str, int], PendingInput] = {}

    def _key(self, user_id: int, scope: PendingScope | str | None) -> tuple[str, int]:
        if scope is None:
            name = PendingScope.USER.value
        elif isinstance(scope, PendingScope):
            name = scope.value
        else:
            name = scope
        return name, user_id

    def _is_expired(self, item: PendingInput) -> bool:
        return (time.time() - item.created_at) > self.ttl_seconds

    def get(self, user_id: int, kind: Optional[PendingInputKind] = None, *, scope: PendingScope | str | None = None) -> Optional[PendingInput]:
        """Возвращает текущую запись ввода, если она не истекла по TTL."""
        key = self._key(user_id, scope)
        item = self._items.get(key)
        if not item:
            return None
        if self._is_expired(item):
            self._items.pop(key, None)
            return None
        if kind is not None and item.kind != kind:
            return None
        return item

    def set(self, user_id: int, pending_input: PendingInput, *, scope: PendingScope | str | None = None) -> None:
        """Устанавливает режим ожидания ввода в выбранном scope."""
        self._items[self._key(user_id, scope)] = pending_input

    def clear(self, user_id: int, *, scope: PendingScope | str | None = None) -> Optional[PendingInput]:
        """Очищает только указанный scope и не трогает соседние контуры."""
        return self._items.pop(self._key(user_id, scope), None)

    def is_active(self, user_id: int, kind: Optional[PendingInputKind] = None, *, scope: PendingScope | str | None = None) -> bool:
        """Проверяет активность режима ввода с учётом TTL."""
        return self.get(user_id, kind, scope=scope) is not None

    def purge_expired(self) -> int:
        """Периодическая очистка протухших записей. Возвращает количество удалённых."""
        now = time.time()
        expired_keys = [
            key for key, item in self._items.items()
            if (now - item.created_at) > self.ttl_seconds
        ]
        for key in expired_keys:
            self._items.pop(key, None)
        return len(expired_keys)
