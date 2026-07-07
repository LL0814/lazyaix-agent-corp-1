"""Outbox store abstraction and in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from events.schema import Event


@dataclass
class OutboxRecord:
    id: int
    event_id: str
    aggregate_id: str
    event_type: str
    topic: str
    message_key: str | None
    payload: dict[str, Any]
    headers: dict[str, Any]
    retry_count: int
    published: bool = False
    failed: bool = False


class OutboxStore(Protocol):
    """Persist outbox events until they are published."""

    async def enqueue(
        self, event: Event, topic: str, key: str | None = None
    ) -> None: ...
    async def poll_pending(self, limit: int) -> list[OutboxRecord]: ...
    async def mark_published(self, outbox_id: int) -> None: ...
    async def mark_failed(self, outbox_id: int, error: str) -> None: ...


class InMemoryOutboxStore:
    """Process-local outbox store used for single-process deployments."""

    def __init__(self):
        self._records: dict[int, OutboxRecord] = {}
        self._next_id = 1

    async def enqueue(
        self, event: Event, topic: str, key: str | None = None
    ) -> None:
        record = OutboxRecord(
            id=self._next_id,
            event_id=event.event_id,
            aggregate_id=event.aggregate_id or event.workflow_id,
            event_type=event.event_type,
            topic=topic,
            message_key=key,
            payload=event.to_dict(),
            headers={},
            retry_count=0,
        )
        self._records[self._next_id] = record
        self._next_id += 1

    async def poll_pending(self, limit: int) -> list[OutboxRecord]:
        return [
            r
            for r in self._records.values()
            if not r.published and not r.failed
        ][:limit]

    async def mark_published(self, outbox_id: int) -> None:
        record = self._records.get(outbox_id)
        if record is not None:
            record.published = True

    async def mark_failed(self, outbox_id: int, error: str) -> None:
        record = self._records.get(outbox_id)
        if record is not None:
            record.failed = True
            record.retry_count += 1
