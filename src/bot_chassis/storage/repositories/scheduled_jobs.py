"""Атомарный claim фоновых заданий сети: один INSERT на слот."""

from __future__ import annotations

from ..engine import StorageEngine, utc_now


class ScheduledJobRunsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    async def claim(
        self,
        bot_id: str,
        job_key: str,
        scheduled_for: str,
        claimed_by: str,
        *,
        stale_after_seconds: float | None = None,
    ) -> bool:
        """Захватывает новый либо протухший незавершённый слот."""

        def _op(conn) -> bool:
            now = utc_now()
            if stale_after_seconds is None:
                conflict_sql = "DO NOTHING"
                params = (bot_id, job_key, scheduled_for, claimed_by, now)
            else:
                stale_modifier = f"-{max(1, int(stale_after_seconds))} seconds"
                conflict_sql = """
                DO UPDATE SET
                    claimed_by = excluded.claimed_by,
                    started_at = excluded.started_at,
                    completed_at = NULL,
                    status = 'claimed',
                    details = NULL
                WHERE scheduled_job_runs.status IN ('claimed', 'running')
                  AND scheduled_job_runs.started_at <= datetime('now', ?)
                """
                params = (bot_id, job_key, scheduled_for, claimed_by, now, stale_modifier)
            cur = conn.execute(
                f"""
                INSERT INTO scheduled_job_runs (
                    bot_id, job_key, scheduled_for, claimed_by, started_at, status
                ) VALUES (?, ?, ?, ?, ?, 'claimed')
                ON CONFLICT(bot_id, job_key, scheduled_for) {conflict_sql}
                """,
                params,
            )
            return cur.rowcount == 1

        return await self._engine.run(_op)

    async def mark_status(
        self,
        bot_id: str,
        job_key: str,
        scheduled_for: str,
        status: str,
        *,
        details: str | None = None,
        complete: bool = False,
        expected_claimed_by: str | None = None,
    ) -> int:
        def _op(conn) -> int:
            now = utc_now()
            owner_sql = " AND claimed_by = ?" if expected_claimed_by is not None else ""
            owner_params = (expected_claimed_by,) if expected_claimed_by is not None else ()
            if complete:
                cur = conn.execute(
                    f"""
                    UPDATE scheduled_job_runs
                    SET status = ?, details = ?, completed_at = ?
                    WHERE bot_id = ? AND job_key = ? AND scheduled_for = ?
                    {owner_sql}
                    """,
                    (status, details, now, bot_id, job_key, scheduled_for, *owner_params),
                )
            else:
                cur = conn.execute(
                    f"""
                    UPDATE scheduled_job_runs
                    SET status = ?, details = ?
                    WHERE bot_id = ? AND job_key = ? AND scheduled_for = ?
                    {owner_sql}
                    """,
                    (status, details, bot_id, job_key, scheduled_for, *owner_params),
                )
            return int(cur.rowcount)

        return await self._engine.run(_op)

    async def get(
        self,
        bot_id: str,
        job_key: str,
        scheduled_for: str,
    ) -> dict | None:
        def _op(conn) -> dict | None:
            row = conn.execute(
                """
                SELECT bot_id, job_key, scheduled_for, claimed_by,
                       started_at, completed_at, status, details
                FROM scheduled_job_runs
                WHERE bot_id = ? AND job_key = ? AND scheduled_for = ?
                """,
                (bot_id, job_key, scheduled_for),
            ).fetchone()
            return dict(row) if row else None

        return await self._engine.run(_op)

    async def latest_done(
        self,
        bot_id: str,
        job_key: str,
    ) -> dict | None:
        """Последний успешный слот по scheduled_for — граница следующего периода."""

        def _op(conn) -> dict | None:
            row = conn.execute(
                """
                SELECT bot_id, job_key, scheduled_for, claimed_by,
                       started_at, completed_at, status, details
                FROM scheduled_job_runs
                WHERE bot_id = ? AND job_key = ? AND status = 'done'
                ORDER BY scheduled_for DESC
                LIMIT 1
                """,
                (bot_id, job_key),
            ).fetchone()
            return dict(row) if row else None

        return await self._engine.run(_op)

    async def earliest(
        self,
        bot_id: str,
        job_key: str,
    ) -> dict | None:
        """Первый когда-либо заявленный слот нужен для периода после неудачи."""

        def _op(conn) -> dict | None:
            row = conn.execute(
                """
                SELECT bot_id, job_key, scheduled_for, claimed_by,
                       started_at, completed_at, status, details
                FROM scheduled_job_runs
                WHERE bot_id = ? AND job_key = ?
                ORDER BY scheduled_for ASC
                LIMIT 1
                """,
                (bot_id, job_key),
            ).fetchone()
            return dict(row) if row else None

        return await self._engine.run(_op)
