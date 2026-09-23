"""
Диспетчер параллельных задач и защита от дребезга кликов (bot_chassis.dispatcher).
Реализует проверенный паттерн из tg_chat_listener:
- Дедупликация повторных нажатий на одну и ту же кнопку меню во время обработки запроса.
- Безопасная отмена (cancel) зависшего таска, если пользователь нажал другую кнопку меню.
"""

import asyncio
from typing import Dict, Optional, Tuple
from loguru import logger


class ActiveTaskTracker:
    """
    Отслеживает активные асинхронные задачи обработки меню для каждого пользователя.
    Гарантирует защиту от гонок и дублей при активном нажатии кнопок.
    """
    def __init__(self):
        self._active_tasks: Dict[int, asyncio.Task] = {}
        self._active_routes: Dict[int, str] = {}

    def should_process(
        self,
        user_id: int,
        route_name: str,
        current_task: asyncio.Task,
    ) -> bool:
        """
        Проверяет, нужно ли обрабатывать входящее событие:
        - Если предыдущая задача для этого пользователя еще выполняется:
          - Нажата та же самая кнопка -> игнорируем (дубль клика), возвращаем False.
          - Нажата другая кнопка -> отменяем предыдущую задачу, сохраняем новую, возвращаем True.
        - Если предыдущих задач нет -> регистрируем новую, возвращаем True.
        """
        prev_task = self._active_tasks.get(user_id)
        prev_route = self._active_routes.get(user_id)

        if prev_task is not None and not prev_task.done() and prev_task is not current_task:
            if prev_route == route_name:
                logger.info(f"⚡ [Deduplication] Игнорируем повторное нажатие {route_name} от пользователя {user_id}")
                return False
            
            # Пользователь переключился на другой экран — отменяем старый расчет
            prev_task.cancel()
            logger.info(f"🔄 [Task Replaced] Отменена предыдущая задача {prev_route}, переключаемся на {route_name} (User: {user_id})")

        self._active_tasks[user_id] = current_task
        self._active_routes[user_id] = route_name
        return True

    def release(self, user_id: int, current_task: asyncio.Task) -> None:
        """Освобождает регистрацию задачи после ее завершения."""
        if self._active_tasks.get(user_id) is current_task:
            self._active_tasks.pop(user_id, None)
            self._active_routes.pop(user_id, None)


# Глобальный синглтон трекера задач
_SHARED_TASK_TRACKER = ActiveTaskTracker()


def get_task_tracker() -> ActiveTaskTracker:
    """Возвращает общий синглтон трекера активных задач меню."""
    return _SHARED_TASK_TRACKER
