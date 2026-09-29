"""Неизменяемые счётные события рамы для периодических отчётов."""

from __future__ import annotations

from ..engine import StorageEngine, utc_now


class ChassisEventsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def record(
        self,
        bot_id: str,
        event_type: str,
        *,
        origin_bot_id: str = "",
        telegram_bot_id: int = 0,
        details: str | None = None,
    ) -> None:
        def _op(conn) -> None:
            conn.execute(
                """
                INSERT INTO chassis_events (
                    bot_id, event_type, origin_bot_id,
                    telegram_bot_id, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_id,
                    event_type,
                    origin_bot_id,
                    telegram_bot_id,
                    details[:200] if details else None,
                    utc_now(),
                ),
            )

        await self._engine.run(_op)
