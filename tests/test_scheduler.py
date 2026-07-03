import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from scheduler import Scheduler


@pytest.mark.asyncio
async def test_scheduler_routes_researcher():
    bus = InMemoryEventBus()
    calls = []

    async def researcher_handler(event: Event):
        calls.append(("researcher", event.task_id))

    async def writer_handler(event: Event):
        calls.append(("writer", event.task_id))

    scheduler = Scheduler(
        bus, {"researcher": researcher_handler, "writer": writer_handler}
    )
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.TASK_ASSIGNED, lambda e: None)
    await bus.start()

    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            target_capability="researcher",
        )
    )
    await asyncio.sleep(0.05)

    assert calls == [("researcher", "r1")]
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_no_duplicate_dispatch():
    bus = InMemoryEventBus()
    calls = []

    async def researcher_handler(event: Event):
        calls.append(event.task_id)

    scheduler = Scheduler(bus, {"researcher": researcher_handler})
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.TASK_ASSIGNED, lambda e: None)
    await bus.start()

    event = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="r1",
        target_capability="researcher",
    )
    await bus.publish(event)
    await bus.publish(event)
    await asyncio.sleep(0.05)

    assert calls == ["r1"]
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_unknown_capability():
    bus = InMemoryEventBus()
    failed = []
    bus.subscribe(EventType.TASK_READY, Scheduler(bus, {}).handle_task_ready)
    bus.subscribe(EventType.AGENT_FAILED, lambda e: failed.append(e))
    await bus.start()

    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            target_capability="unknown",
        )
    )
    await asyncio.sleep(0.05)

    assert len(failed) == 1
    assert "Unknown capability" in failed[0].payload["error"]
    await bus.stop()
