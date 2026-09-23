"""Рубильник: is_maintenance + maintenance_reason на bot_id."""

from __future__ import annotations

from typing import Optional

from ..engine import StorageEngine, utc_now


class BotSettingsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def get_maintenance_status(self, bot_id: str) -> tuple[bool, Optional[str]]:
        def _op(conn) -> tuple[bool, Optional[str]]:
            row = conn.execute(
                "SELECT is_maintenance, maintenance_reason FROM bot_settings WHERE bot_id = ?",
                (bot_id,),
            ).fetchone()
            if not row:
                return False, None
            return bool(row["is_maintenance"]), row["maintenance_reason"]

        return await self._engine.run(_op)

    async def set_maintenance_status(
        self,
        bot_id: str,
        is_maintenance: bool,
        reason: Optional[str] = None,
        updated_by: Optional[int] = None,
    ) -> None:
        def _op(conn) -> None:
            conn.execute(
                """
                INSERT INTO bot_settings (bot_id, is_maintenance, maintenance_reason, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    is_maintenance = excluded.is_maintenance,
                    maintenance_reason = excluded.maintenance_reason,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id,
                    1 if is_maintenance else 0,
                    reason if is_maintenance else None,
                    updated_by,
                    utc_now(),
                ),
            )

        await self._engine.run(_op)
