"""PostgreSQL implementation of the OutboxStore protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import asyncpg

from events.outbox import OutboxRecord
from events.schema import Event


class PostgresOutboxRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def enqueue(
        self,
        event: Event,
        topic: str,
        key: str | None = None,
        conn: asyncpg.Connection | None = None,
    ) -> None:
        payload = event.to_dict()
        headers = {
            "event_id": event.event_id,
            "trace_id": event.trace_id,
            "workflow_id": event.workflow_id,
        }
        executor = conn if conn is not None else self._pool
        await executor.execute(
            """
            INSERT INTO outbox_events (
                event_id, aggregate_id, event_type, topic, message_key,
                payload, headers, status, next_retry_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW())
            ON CONFLICT (event_id) DO NOTHING
            """,
            event.event_id,
            event.aggregate_id or event.workflow_id,
            event.event_type,
            topic,
            key,
            json.dumps(payload),
            json.dumps(headers),
        )

    async def poll_pending(self, limit: int = 100) -> list[OutboxRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, event_id, aggregate_id, event_type, topic,
                    message_key, payload, headers, retry_count
                FROM outbox_events
                WHERE status = 'pending' AND next_retry_at <= NOW()
                ORDER BY id
                LIMIT $1
                FOR UPDATE SKIP LOCKED
                """,
                limit,
            )
            return [
                OutboxRecord(
                    id=row["id"],
                    event_id=str(row["event_id"]),
                    aggregate_id=str(row["aggregate_id"]),
                    event_type=row["event_type"],
                    topic=row["topic"],
                    message_key=row["message_key"],
                    payload=json.loads(row["payload"]),
                    headers=json.loads(row["headers"]),
                    retry_count=row["retry_count"],
                )
                for row in rows
            ]

    async def mark_published(
        self, outbox_id: int, conn: asyncpg.Connection | None = None
    ) -> None:
        executor = conn if conn is not None else self._pool
        await executor.execute(
            """
            UPDATE outbox_events
            SET status = 'published', published_at = NOW()
            WHERE id = $1
            """,
            outbox_id,
        )

    async def mark_failed(self, outbox_id: int, error: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox_events
                SET retry_count = retry_count + 1,
                    next_retry_at = NOW() + (2 ^ retry_count) * INTERVAL '1 second',
                    error_info = $2
                WHERE id = $1
                """,
                outbox_id,
                error,
            )
