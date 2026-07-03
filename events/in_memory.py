"""In-memory EventBus implementation using asyncio.Queue."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from events.schema import Event

logger = logging.getLogger(__name__)


class InMemoryEventBus:
    """Process-local event bus. Each event type/handler has its own queue and consumer task."""

    def __init__(self):
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._queues: dict[str, list[asyncio.Queue[Event]]] = {}
        self._tasks: list[asyncio.Task] = []

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        self._queues.setdefault(event_type, []).append(asyncio.Queue())

    async def publish(self, event: Event) -> None:
        for queue in self._queues.setdefault(event.event_type, []):
            await queue.put(event)

    async def start(self) -> None:
        for event_type, handlers in self._handlers.items():
            for idx, handler in enumerate(handlers):
                queue = self._queues[event_type][idx]
                self._tasks.append(
                    asyncio.create_task(
                        self._consume(event_type, queue, handler),
                        name=f"consumer-{event_type}-{len(self._tasks)}",
                    )
                )

    async def _consume(
        self,
        event_type: str,
        queue: asyncio.Queue[Event],
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        while True:
            try:
                event = await queue.get()
            except asyncio.CancelledError:
                break
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Handler error for event_type=%s event_id=%s",
                    event_type,
                    event.event_id,
                )
            finally:
                queue.task_done()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
