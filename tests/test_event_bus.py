import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType


@pytest.mark.asyncio
async def test_publish_consume():
    bus = InMemoryEventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe(EventType.TASK_READY, handler)
    await bus.start()

    event = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="t1",
    )
    await bus.publish(event)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].task_id == "t1"

    await bus.stop()


@pytest.mark.asyncio
async def test_handler_exception_not_crash_bus():
    bus = InMemoryEventBus()
    received = []

    async def failer(event: Event):
        raise RuntimeError("boom")

    async def keeper(event: Event):
        received.append(event)

    bus.subscribe(EventType.TASK_READY, failer)
    bus.subscribe(EventType.TASK_READY, keeper)
    await bus.start()

    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
        )
    )
    await asyncio.sleep(0.05)

    assert len(received) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_start_stop():
    bus = InMemoryEventBus()

    async def noop_handler(event: Event):
        return None

    bus.subscribe(EventType.TASK_READY, noop_handler)
    await bus.start()
    assert len(bus._tasks) == 1
    await bus.stop()
    assert len(bus._tasks) == 0
