import asyncio

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from workflow.coordinator import WorkflowCoordinator
from workflow.state import Task, TaskStatus, Workflow


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
