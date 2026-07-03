"""EventBus abstract protocol."""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from events.schema import Event


class EventBus(Protocol):
    """Abstract event bus: implementations may use queues, Redis, etc."""

    async def publish(self, event: Event) -> None:
        ...

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        ...

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...
