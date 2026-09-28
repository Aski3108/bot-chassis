"""Статус пользователя в конкретном Telegram-боте. Санкции сети здесь не хранятся."""

from __future__ import annotations

from dataclasses import dataclass

from ..engine import StorageEngine, utc_now


@dataclass(frozen=True, slots=True)
class ProcessOrigin:
    origin_bot_id: str
    telegram_bot_id: int


@dataclass(frozen=True, slots=True)
class UserBotStatus:
    origin_bot_id: str
    telegram_bot_id: int
    status: str


class UserBotStatusRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine
        self._process: ProcessOrigin | None = None

    def bind_process(self, origin_bot_id: str, telegram_bot_id: int) -> None:
        """Запоминает origin этого процесса после фактического bot.id."""
        self._process = ProcessOrigin(origin_bot_id=origin_bot_id, telegram_bot_id=telegram_bot_id)

    @property
    def process(self) -> ProcessOrigin | None:
        return self._process

    async def mark_active(
        self,
        bot_id: str,
        user_id: int,
        origin_bot_id: str,
        telegram_bot_id: int,
    ) -> bool:
        """Подтверждает active. True — ряда ещё не было, это первый запуск в этом боте."""
        return await self._upsert(bot_id, user_id, origin_bot_id, telegram_bot_id, "active", None)

    async def mark_stopped(
        self,
        bot_id: str,
        user_id: int,
        origin_bot_id: str,
        telegram_bot_id: int,
        error_code: str,
    ) -> None:
        await self._upsert(bot_id, user_id, origin_bot_id, telegram_bot_id, "stopped", error_code)

    async def mark_deleted(
        self,
        bot_id: str,
        user_id: int,
        origin_bot_id: str,
        telegram_bot_id: int,
    ) -> None:
        """deleted на всех уже известных ботах tenant и на боте, который увидел ошибку."""

        def _op(conn) -> None:
            now = utc_now()
            conn.execute(
                """
                UPDATE user_bot_statuses
                SET status = 'deleted',
                    status_changed_at = ?,
                    last_seen_at = ?,
                    last_error_code = 'deactivated'
                WHERE bot_id = ? AND user_id = ?
                """,
                (now, now, bot_id, user_id),
            )
            _upsert_status(
                conn,
                bot_id,
                user_id,
                origin_bot_id,
                telegram_bot_id,
                "deleted",
                "deactivated",
                now,
            )

        await self._engine.run(_op)

    async def list_for_user(self, bot_id: str, user_id: int) -> list[UserBotStatus]:
        def _op(conn) -> list[UserBotStatus]:
            rows = conn.execute(
                """
                SELECT origin_bot_id, telegram_bot_id, status
                FROM user_bot_statuses
                WHERE bot_id = ? AND user_id = ?
                ORDER BY telegram_bot_id ASC
                """,
                (bot_id, user_id),
            ).fetchall()
            return [
                UserBotStatus(
                    origin_bot_id=row["origin_bot_id"],
                    telegram_bot_id=int(row["telegram_bot_id"]),
                    status=row["status"],
                )
                for row in rows
            ]

        return await self._engine.run(_op)

    async def list_known_bots(self, bot_id: str) -> list[ProcessOrigin]:
        def _op(conn) -> list[ProcessOrigin]:
            rows = conn.execute(
                """
                SELECT origin_bot_id, telegram_bot_id
                FROM user_bot_statuses
                WHERE bot_id = ?
                GROUP BY telegram_bot_id
                ORDER BY telegram_bot_id ASC
                """,
                (bot_id,),
            ).fetchall()
            return [
                ProcessOrigin(
                    origin_bot_id=row["origin_bot_id"],
                    telegram_bot_id=int(row["telegram_bot_id"]),
                )
                for row in rows
            ]

        known = await self._engine.run(_op)
        process = self._process
        if process is not None and all(item.telegram_bot_id != process.telegram_bot_id for item in known):
            known.append(process)
            known.sort(key=lambda item: item.telegram_bot_id)
        return known

    async def _upsert(
        self,
        bot_id: str,
        user_id: int,
        origin_bot_id: str,
        telegram_bot_id: int,
        status: str,
        error_code: str | None,
    ) -> bool:
        def _op(conn) -> bool:
            return _upsert_status(
                conn,
                bot_id,
                user_id,
                origin_bot_id,
                telegram_bot_id,
                status,
                error_code,
                utc_now(),
            )

        return await self._engine.run(_op)


def _upsert_status(
    conn,
    bot_id: str,
    user_id: int,
    origin_bot_id: str,
    telegram_bot_id: int,
    status: str,
    error_code: str | None,
    now: str,
) -> bool:
    row = conn.execute(
        """
        SELECT status FROM user_bot_statuses
        WHERE bot_id = ? AND user_id = ? AND telegram_bot_id = ?
        """,
        (bot_id, user_id, telegram_bot_id),
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO user_bot_statuses (
                bot_id, user_id, origin_bot_id, telegram_bot_id, status,
                first_seen_at, last_seen_at, status_changed_at, last_error_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bot_id, user_id, origin_bot_id, telegram_bot_id, status, now, now, now, error_code),
        )
        return True
    if row["status"] == status:
        conn.execute(
            """
            UPDATE user_bot_statuses
            SET last_seen_at = ?, origin_bot_id = ?
            WHERE bot_id = ? AND user_id = ? AND telegram_bot_id = ?
            """,
            (now, origin_bot_id, bot_id, user_id, telegram_bot_id),
        )
        return False
    conn.execute(
        """
        UPDATE user_bot_statuses
        SET status = ?, origin_bot_id = ?, last_seen_at = ?, status_changed_at = ?, last_error_code = ?
        WHERE bot_id = ? AND user_id = ? AND telegram_bot_id = ?
        """,
        (status, origin_bot_id, now, now, error_code, bot_id, user_id, telegram_bot_id),
    )
    return False
