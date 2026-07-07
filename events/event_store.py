"""Event store abstraction and in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from events.schema import Event


class EventStore(Protocol):
    """Append-only event store for auditing and debugging."""

    async def append(self, event: Event) -> None: ...


class InMemoryEventStore:
    """Process-local event store used for tests and single-process deployments."""

    def __init__(self):
        self._events: list[Event] = []

    async def append(self, event: Event) -> None:
        self._events.append(event)
