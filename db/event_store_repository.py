"""PostgreSQL implementation of the EventStore protocol."""

from __future__ import annotations

import json

import asyncpg

from events.schema import Event


class EventStoreRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def append(self, event: Event) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_store (
                    event_id, trace_id, parent_event_id, aggregate_id, event_type,
                    priority, timestamp, source, target_agent, target_capability,
                    workflow_id, task_id, payload, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (event_id) DO NOTHING
                """,
                event.event_id,
                event.trace_id,
                event.parent_event_id,
                event.aggregate_id or event.workflow_id,
                event.event_type,
                event.priority,
                event.timestamp,
                event.source,
                event.target_agent,
                event.target_capability,
                event.workflow_id,
                event.task_id,
                json.dumps(event.payload),
                json.dumps(event.metadata),
            )
