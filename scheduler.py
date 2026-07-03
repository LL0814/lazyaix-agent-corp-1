"""Deterministic scheduler: routes task.ready events to agent handlers by capability."""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from events.bus import EventBus
from events.schema import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class Scheduler:
    """Routes ready tasks to handlers based on target_capability."""

    def __init__(self, event_bus: EventBus, handlers: dict[str, Handler]):
        self.event_bus = event_bus
        self.handlers = handlers
        self._dispatched: set[str] = set()

    async def handle_task_ready(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            logger.error("task.ready event without task_id: %s", event.event_id)
            return

        dispatch_key = f"{event.workflow_id}:{task_id}"
        if dispatch_key in self._dispatched:
            logger.debug("Task %s already dispatched, ignoring", task_id)
            return
        self._dispatched.add(dispatch_key)

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
        await handler(event)
