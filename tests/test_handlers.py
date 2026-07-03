import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from models import Model
from subagents.handlers import ResearcherHandler, WriterHandler


@pytest.mark.asyncio
async def test_researcher_handler_publishes_completed():
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(EventType.AGENT_COMPLETED, lambda e: received.append(e))
    bus.subscribe(EventType.AGENT_STARTED, lambda e: None)
    await bus.start()

    handler = ResearcherHandler(Model(), bus)
    await handler(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            target_capability="researcher",
            payload={"instructions": "research AI"},
        )
    )
    await asyncio.sleep(0.05)

    completed = [e for e in received if e.event_type == EventType.AGENT_COMPLETED]
    assert len(completed) == 1
    assert completed[0].task_id == "r1"
    assert "[Researcher]" in completed[0].payload["result"]

    await bus.stop()


@pytest.mark.asyncio
async def test_writer_handler_publishes_completed():
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(EventType.AGENT_COMPLETED, lambda e: received.append(e))
    bus.subscribe(EventType.AGENT_STARTED, lambda e: None)
    await bus.start()

    handler = WriterHandler(Model(), bus)
    await handler(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="w1",
            target_capability="writer",
            payload={"instructions": "write poem"},
        )
    )
    await asyncio.sleep(0.05)

    completed = [e for e in received if e.event_type == EventType.AGENT_COMPLETED]
    assert len(completed) == 1
    assert completed[0].task_id == "w1"
    assert "[Writer]" in completed[0].payload["result"]

    await bus.stop()
