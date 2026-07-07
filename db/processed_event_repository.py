"""PostgreSQL implementation of processed-events inbox store."""

from __future__ import annotations

import asyncpg


class ProcessedEventRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def is_processed(self, event_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM processed_events WHERE event_id = $1",
                event_id,
            )
            return row is not None

    async def mark_processed(
        self,
        event_id: str,
        workflow_id: str,
        event_type: str,
        *,
        task_id: str | None = None,
        conn: asyncpg.Connection | None = None,
    ) -> None:
        executor = conn if conn is not None else self._pool
        await executor.execute(
            """
            INSERT INTO processed_events (event_id, workflow_id, task_id, event_type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (event_id) DO NOTHING
            """,
            event_id,
            workflow_id,
            task_id,
            event_type,
        )
