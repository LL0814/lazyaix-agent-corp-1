import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from workflow.coordinator import WorkflowCoordinator
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


def make_wf(*tasks: Task) -> Workflow:
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


@pytest.mark.asyncio
async def test_coordinator_publishes_ready_tasks():
    bus = InMemoryEventBus()
    ready_events = []
    bus.subscribe(EventType.TASK_READY, lambda e: ready_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("r1", "research", "researcher", "do research"))
    await coord.start_workflow(wf)
    await asyncio.sleep(0.05)

    assert len(ready_events) == 1
    assert ready_events[0].task_id == "r1"
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_triggers_downstream():
    bus = InMemoryEventBus()
    ready_events = []
    completed_events = []
    bus.subscribe(EventType.TASK_READY, lambda e: ready_events.append(e))
    bus.subscribe(EventType.WORKFLOW_COMPLETED, lambda e: completed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    r1 = Task("r1", "research", "researcher", "do research")
    w1 = Task("w1", "write", "writer", "write", dependencies=["r1"])
    wf = make_wf(r1, w1)
    await coord.start_workflow(wf)

    # 模拟 Researcher 完成。
    await coord.handle_task_completed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_COMPLETED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            source="researcher",
            payload={"result": "research result"},
        )
    )
    await asyncio.sleep(0.05)

    assert any(e.task_id == "w1" for e in ready_events)
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_workflow_completed():
    bus = InMemoryEventBus()
    completed = []
    bus.subscribe(EventType.WORKFLOW_COMPLETED, lambda e: completed.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("w1", "write", "writer", "write"))
    await coord.start_workflow(wf)
    await coord.handle_task_completed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_COMPLETED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="w1",
            source="writer",
            payload={"result": "done"},
        )
    )
    await asyncio.sleep(0.05)

    assert len(completed) == 1
    assert wf.status.name == "COMPLETED"
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_retries_failed_task():
    bus = InMemoryEventBus()
    ready_events = []
    completed_events = []
    bus.subscribe(EventType.TASK_READY, lambda e: ready_events.append(e))
    bus.subscribe(EventType.WORKFLOW_COMPLETED, lambda e: completed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await coord.start_workflow(wf)
    await asyncio.sleep(0.05)

    assert len(ready_events) == 1
    ready_events.clear()

    await coord.handle_task_failed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_FAILED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            source="worker",
            payload={"error": "oops", "retryable": True},
        )
    )
    await asyncio.sleep(0.05)

    assert wf.tasks["t1"].status == TaskStatus.DISPATCHED
    assert len(ready_events) == 1
    assert ready_events[0].metadata.get("retry_count") == 1

    await coord.handle_task_completed(
        Event(
            event_id="e2",
            event_type=EventType.AGENT_COMPLETED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            source="worker",
            payload={"result": "done"},
        )
    )
    await asyncio.sleep(0.05)

    assert wf.tasks["t1"].status == TaskStatus.COMPLETED
    assert wf.status == WorkflowStatus.COMPLETED
    assert len(completed_events) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_blocks_downstream_on_failure():
    bus = InMemoryEventBus()
    failed_events = []
    bus.subscribe(EventType.WORKFLOW_FAILED, lambda e: failed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    t1 = Task("t1", "work", "worker", "do work")
    t2 = Task("t2", "work", "worker", "do more", dependencies=["t1"])
    wf = make_wf(t1, t2)
    await coord.start_workflow(wf)

    await coord.handle_task_failed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_FAILED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            source="worker",
            payload={"error": "fatal", "retryable": False},
        )
    )
    await asyncio.sleep(0.05)

    assert wf.tasks["t1"].status == TaskStatus.FAILED
    assert wf.tasks["t2"].status == TaskStatus.BLOCKED
    assert wf.status == WorkflowStatus.FAILED
    assert len(failed_events) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_ignores_duplicate_completed():
    bus = InMemoryEventBus()
    completed_events = []
    bus.subscribe(EventType.WORKFLOW_COMPLETED, lambda e: completed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await coord.start_workflow(wf)

    event = Event(
        event_id="e1",
        event_type=EventType.AGENT_COMPLETED,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="t1",
        source="worker",
        payload={"result": "done"},
    )
    await coord.handle_task_completed(event)
    await coord.handle_task_completed(event)
    await asyncio.sleep(0.05)

    assert wf.tasks["t1"].status == TaskStatus.COMPLETED
    assert len(completed_events) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_future_resolved_on_completion():
    bus = InMemoryEventBus()
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    future = coord.create_future(wf.workflow_id)
    coord.set_completion_future(wf.workflow_id, future)

    await coord.start_workflow(wf)
    await coord.handle_task_completed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_COMPLETED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="t1",
            source="worker",
            payload={"result": "done"},
        )
    )
    await asyncio.sleep(0.05)

    assert future.done()
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_duplicate_workflow_failed_ignored():
    bus = InMemoryEventBus()
    failed_events = []
    bus.subscribe(EventType.WORKFLOW_FAILED, lambda e: failed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await coord.start_workflow(wf)

    event = Event(
        event_id="e1",
        event_type=EventType.AGENT_FAILED,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="t1",
        source="worker",
        payload={"error": "fatal", "retryable": False},
    )
    await coord.handle_task_failed(event)
    await coord.handle_task_failed(event)
    await asyncio.sleep(0.05)

    assert wf.tasks["t1"].status == TaskStatus.FAILED
    assert wf.status == WorkflowStatus.FAILED
    assert len(failed_events) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_coordinator_retry_exhaustion_blocks_downstream():
    bus = InMemoryEventBus()
    failed_events = []
    bus.subscribe(EventType.WORKFLOW_FAILED, lambda e: failed_events.append(e))
    await bus.start()

    coord = WorkflowCoordinator(bus, max_retries=1)
    r1 = Task("r1", "research", "researcher", "do research")
    w1 = Task("w1", "write", "writer", "write", dependencies=["r1"])
    wf = make_wf(r1, w1)
    await coord.start_workflow(wf)
    await asyncio.sleep(0.05)

    await coord.handle_task_failed(
        Event(
            event_id="e1",
            event_type=EventType.AGENT_FAILED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            source="researcher",
            payload={"error": "oops", "retryable": True},
        )
    )
    await asyncio.sleep(0.05)

    await coord.handle_task_failed(
        Event(
            event_id="e2",
            event_type=EventType.AGENT_FAILED,
            trace_id="tr-1",
            workflow_id="wf-1",
            task_id="r1",
            source="researcher",
            payload={"error": "oops again", "retryable": True},
        )
    )
    await asyncio.sleep(0.05)

    assert wf.tasks["r1"].status == TaskStatus.FAILED
    assert wf.tasks["w1"].status == TaskStatus.BLOCKED
    assert wf.status == WorkflowStatus.FAILED
    assert len(failed_events) == 1
    await bus.stop()
