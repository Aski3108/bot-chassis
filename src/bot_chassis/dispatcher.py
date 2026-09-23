"""Диспетчер параллельных задач и защита от дребезга кликов (Button Chassis).

Реализует паттерн защиты от гонок и повторных кликов:
- Дедупликация повторных нажатий на одну и ту же кнопку меню во время обработки запроса.
- Безопасная отмена (cancel) зависшей задачи, если пользователь переключился на другую вкладку.
"""

from __future__ import annotations
import asyncio
from typing import Optional
from loguru import logger


class ActiveTaskTracker:
    """
    Отслеживает активные асинхронные задачи обработки меню для каждого пользователя.
    Создаётся как экземпляр на бота (не разделяется между процессами/ботами).
    """
    def __init__(self) -> None:
        self._active_tasks: dict[int, asyncio.Task] = {}
        self._active_routes: dict[int, str] = {}

    def should_process(
        self,
        user_id: int,
        route_name: str,
        current_task: Optional[asyncio.Task],
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

        is_prev_running = (
            (prev_task is not None and not prev_task.done() and prev_task is not current_task)
            or (prev_task is None and prev_route is not None)
        )

        if is_prev_running:
            if prev_route == route_name:
                logger.info(f"⚡ [Deduplication] Игнорируем повторное нажатие {route_name} от пользователя {user_id}")
                return False
            
            # Пользователь переключился на другой экран — отменяем старый расчет
            if prev_task is not None and not prev_task.done():
                prev_task.cancel()
                logger.info(f"🔄 [Task Cancelled] Отменена предыдущая задача {prev_route}, переключаемся на {route_name} (User: {user_id})")

        if current_task is not None:
            self._active_tasks[user_id] = current_task
        self._active_routes[user_id] = route_name
        return True

    def release(self, user_id: int, current_task: Optional[asyncio.Task]) -> None:
        """Освобождает регистрацию задачи после ее завершения."""
        if current_task is not None:
            if self._active_tasks.get(user_id) is current_task:
                self._active_tasks.pop(user_id, None)
                self._active_routes.pop(user_id, None)
        else:
            self._active_tasks.pop(user_id, None)
            self._active_routes.pop(user_id, None)
