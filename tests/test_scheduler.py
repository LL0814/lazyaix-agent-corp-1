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

    async def assigned_noop(event: Event) -> None:
        return None

    bus.subscribe(EventType.TASK_ASSIGNED, assigned_noop)
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
        calls.append((event.task_id, event.metadata.get("retry_count", 0)))

    scheduler = Scheduler(bus, {"researcher": researcher_handler})
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)

    async def assigned_noop(event: Event) -> None:
        return None

    bus.subscribe(EventType.TASK_ASSIGNED, assigned_noop)
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

    assert calls == [("r1", 0)]

    retry_event = Event(
        event_id="e2",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="r1",
        target_capability="researcher",
        metadata={"retry_count": 1},
    )
    await bus.publish(retry_event)
    await asyncio.sleep(0.05)

    assert calls == [("r1", 0), ("r1", 1)]
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_unknown_capability():
    bus = InMemoryEventBus()
    failed = []

    async def collect_failed(event: Event) -> None:
        failed.append(event)

    bus.subscribe(EventType.TASK_READY, Scheduler(bus, {}).handle_task_ready)
    bus.subscribe(EventType.AGENT_FAILED, collect_failed)
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


@pytest.mark.asyncio
async def test_scheduler_dispatches_ready_tasks_concurrently():
    bus = InMemoryEventBus()
    done = asyncio.Event()
    calls = []
    handler_count = 2

    async def slow_handler(event: Event):
        calls.append(("start", event.task_id, asyncio.get_event_loop().time()))
        await asyncio.sleep(0.1)
        calls.append(("end", event.task_id, asyncio.get_event_loop().time()))
        if len([c for c in calls if c[0] == "end"]) == handler_count:
            done.set()

    scheduler = Scheduler(
        bus,
        {
            "cap_a": slow_handler,
            "cap_b": slow_handler,
        },
    )
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)

    async def assigned_noop(event: Event) -> None:
        return None

    bus.subscribe(EventType.TASK_ASSIGNED, assigned_noop)
    await bus.start()

    start_time = asyncio.get_event_loop().time()
    await bus.publish(
        Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            target_capability="cap_a",
        )
    )
    await bus.publish(
        Event(
            event_id="e2",
            event_type=EventType.TASK_READY,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t2",
            target_capability="cap_b",
        )
    )

    await asyncio.wait_for(done.wait(), timeout=1.0)
    elapsed = asyncio.get_event_loop().time() - start_time

    assert len([c for c in calls if c[0] == "end"]) == handler_count
    assert elapsed < 0.2
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_handler_exception_logged(caplog):
    bus = InMemoryEventBus()
    calls = []

    async def failing_handler(event: Event):
        calls.append(event.task_id)
        raise RuntimeError("handler exploded")

    scheduler = Scheduler(bus, {"researcher": failing_handler})
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)

    async def assigned_noop(event: Event) -> None:
        return None

    bus.subscribe(EventType.TASK_ASSIGNED, assigned_noop)
    await bus.start()

    with caplog.at_level("ERROR", logger="scheduler"):
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

    assert calls == ["r1"]
    assert "Handler failed for task r1" in caplog.text
    assert "handler exploded" in caplog.text
    await bus.stop()


@pytest.mark.asyncio
async def test_scheduler_cleans_up_completed_handler_tasks():
    bus = InMemoryEventBus()
    calls = []

    async def ok_handler(event: Event):
        calls.append(event.task_id)

    scheduler = Scheduler(bus, {"researcher": ok_handler})
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)

    async def assigned_noop(event: Event) -> None:
        return None

    bus.subscribe(EventType.TASK_ASSIGNED, assigned_noop)
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

    assert calls == ["r1"]
    assert len(scheduler._tasks) == 0
    await bus.stop()
