"""Deterministic scheduler: routes task.ready events to agent handlers by capability."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Awaitable, Callable, Protocol

from events.bus import EventBus
from events.schema import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class IdempotencyStore(Protocol):
    """Abstraction for dispatch deduplication across Scheduler instances."""

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        """Try to acquire the dispatch lock for *key*.

        Returns ``True`` if this caller was the first to acquire the lock
        within the TTL window, ``False`` otherwise.
        """
        ...


class InMemoryIdempotencyStore:
    """Process-local idempotency store used for tests and single-process deployments."""

    def __init__(self):
        self._keys: dict[str, float] = {}

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        # prune expired entries opportunistically
        expired = [k for k, expires_at in self._keys.items() if expires_at <= now]
        for k in expired:
            self._keys.pop(k, None)
        if key in self._keys:
            return False
        self._keys[key] = now + ttl_seconds
        return True


class Scheduler:
    """Routes ready tasks to handlers based on target_capability."""

    def __init__(
        self,
        event_bus: EventBus,
        handlers: dict[str, Handler],
        idempotency_store: IdempotencyStore | None = None,
        dispatch_ttl_seconds: float = 3600.0,
    ):
        self.event_bus = event_bus
        self.handlers = handlers
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._dispatch_ttl_seconds = dispatch_ttl_seconds
        self._tasks: set[asyncio.Task] = set()

    def _spawn_handler(self, handler: Handler, event: Event) -> None:
        task = asyncio.create_task(handler(event))
        self._tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.exception(
                    "Handler failed for task %s", event.task_id, exc_info=exc
                )

        task.add_done_callback(_on_done)

    async def handle_task_ready(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            logger.error("task.ready event without task_id: %s", event.event_id)
            return

        retry_count = event.metadata.get("retry_count", 0)
        dispatch_key = f"{event.workflow_id}:{task_id}:{retry_count}"
        acquired = await self._idempotency.acquire(
            dispatch_key, int(self._dispatch_ttl_seconds)
        )
        if not acquired:
            logger.debug("Task %s already dispatched, ignoring", task_id)
            return

        capability = event.target_capability
        handler = self.handlers.get(capability)
        if handler is None:
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_FAILED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=task_id,
                    source="scheduler",
                    target_capability=capability,
                    payload={"error": f"Unknown capability: {capability}"},
                )
            )
            return

        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.TASK_ASSIGNED,
                trace_id=event.trace_id,
                workflow_id=event.workflow_id,
                task_id=task_id,
                source="scheduler",
                target_capability=capability,
            )
        )
        self._spawn_handler(handler, event)
