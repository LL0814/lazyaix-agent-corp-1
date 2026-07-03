"""Async event handlers for Researcher and Writer workers."""

from __future__ import annotations

import asyncio
import logging
import uuid

from events.bus import EventBus
from events.schema import Event, EventType
from subagents.workers import Researcher, Writer

logger = logging.getLogger(__name__)


class ResearcherHandler:
    def __init__(self, model, event_bus: EventBus):
        self.worker = Researcher(model)
        self.event_bus = event_bus

    async def __call__(self, event: Event) -> None:
        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.AGENT_STARTED,
                trace_id=event.trace_id,
                workflow_id=event.workflow_id,
                task_id=event.task_id,
                source="researcher",
                target_capability="researcher",
            )
        )
        try:
            instructions = event.payload.get("instructions", "")
            result = await asyncio.to_thread(self.worker.run, instructions)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_COMPLETED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="researcher",
                    target_capability="researcher",
                    payload={"result": result},
                )
            )
        except Exception as exc:
            logger.exception("Researcher handler failed for task %s", event.task_id)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_FAILED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="researcher",
                    target_capability="researcher",
                    payload={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "retryable": True,
                    },
                )
            )


class WriterHandler:
    def __init__(self, model, event_bus: EventBus):
        self.worker = Writer(model)
        self.event_bus = event_bus

    async def __call__(self, event: Event) -> None:
        await self.event_bus.publish(
            Event(
                event_id=str(uuid.uuid4()),
                event_type=EventType.AGENT_STARTED,
                trace_id=event.trace_id,
                workflow_id=event.workflow_id,
                task_id=event.task_id,
                source="writer",
                target_capability="writer",
            )
        )
        try:
            instructions = event.payload.get("instructions", "")
            result = await asyncio.to_thread(self.worker.run, instructions)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_COMPLETED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="writer",
                    target_capability="writer",
                    payload={"result": result},
                )
            )
        except Exception as exc:
            logger.exception("Writer handler failed for task %s", event.task_id)
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.AGENT_FAILED,
                    trace_id=event.trace_id,
                    workflow_id=event.workflow_id,
                    task_id=event.task_id,
                    source="writer",
                    target_capability="writer",
                    payload={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "retryable": True,
                    },
                )
            )
