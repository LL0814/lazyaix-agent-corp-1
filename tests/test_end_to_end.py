from __future__ import annotations

import asyncio
from typing import Any

import pytest

from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from scheduler import Scheduler
from subagents.handlers import ResearcherHandler, WriterHandler
from workflow.coordinator import WorkflowCoordinator
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus
from workflow.state_store import InMemoryStateStore


def _make_model_stub(result: str):
    class _StubModel:
        def complete(self, prompt: str) -> str:
            return result

    return _StubModel()


def _writer_plan() -> str:
    return (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "w1", "task_type": "write", "target_capability": "writer", "instructions": "write a poem"}'
        ']}'
    )


def _research_then_write_plan() -> str:
    return (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "r1", "task_type": "research", "target_capability": "researcher", "instructions": "research topic"},'
        '{"task_id": "w1", "task_type": "write", "target_capability": "writer", "instructions": "write report", "dependencies": ["r1"]}'
        ']}'
    )


@pytest.mark.asyncio
async def test_end_to_end_writer_only():
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    model = _make_model_stub("poem result")
    coord = WorkflowCoordinator(bus, store)
    scheduler = Scheduler(
        bus,
        {
            "writer": WriterHandler(model, bus),
        },
    )
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.AGENT_COMPLETED, coord.handle_task_completed)
    bus.subscribe(EventType.AGENT_FAILED, coord.handle_task_failed)
    await bus.start()

    try:
        wf = Workflow(
            workflow_id="wf-writer",
            trace_id="tr-1",
            user_input="write a poem",
            tasks={
                "w1": Task("w1", "write", "writer", "write a poem"),
            },
        )
        future = asyncio.get_running_loop().create_future()
        coord.set_completion_future(wf.workflow_id, future)
        await coord.start_workflow(wf)
        await asyncio.wait_for(future, timeout=2.0)

        assert wf.status == WorkflowStatus.COMPLETED
        assert wf.tasks["w1"].status == TaskStatus.COMPLETED
        assert "poem result" in wf.tasks["w1"].result
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_end_to_end_researcher_then_writer():
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    model = _make_model_stub("report result")
    coord = WorkflowCoordinator(bus, store)
    scheduler = Scheduler(
        bus,
        {
            "researcher": ResearcherHandler(model, bus),
            "writer": WriterHandler(model, bus),
        },
    )
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.AGENT_COMPLETED, coord.handle_task_completed)
    bus.subscribe(EventType.AGENT_FAILED, coord.handle_task_failed)
    await bus.start()

    try:
        wf = Workflow(
            workflow_id="wf-chain",
            trace_id="tr-1",
            user_input="research and write",
            tasks={
                "r1": Task("r1", "research", "researcher", "research topic"),
                "w1": Task(
                    "w1",
                    "write",
                    "writer",
                    "write report",
                    dependencies=["r1"],
                ),
            },
        )
        future = asyncio.get_running_loop().create_future()
        coord.set_completion_future(wf.workflow_id, future)
        await coord.start_workflow(wf)
        await asyncio.wait_for(future, timeout=2.0)

        assert wf.status == WorkflowStatus.COMPLETED
        assert wf.tasks["r1"].status == TaskStatus.COMPLETED
        assert wf.tasks["w1"].status == TaskStatus.COMPLETED
        assert "report result" in wf.tasks["w1"].result
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_end_to_end_parallel_researchers():
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    model = _make_model_stub("parallel result")
    coord = WorkflowCoordinator(bus, store)
    scheduler = Scheduler(
        bus,
        {
            "researcher": ResearcherHandler(model, bus),
            "writer": WriterHandler(model, bus),
        },
    )
    bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus.subscribe(EventType.AGENT_COMPLETED, coord.handle_task_completed)
    bus.subscribe(EventType.AGENT_FAILED, coord.handle_task_failed)
    await bus.start()

    try:
        wf = Workflow(
            workflow_id="wf-parallel",
            trace_id="tr-1",
            user_input="parallel research",
            tasks={
                "r1": Task("r1", "research", "researcher", "research a"),
                "r2": Task("r2", "research", "researcher", "research b"),
            },
        )
        future = asyncio.get_running_loop().create_future()
        coord.set_completion_future(wf.workflow_id, future)
        await coord.start_workflow(wf)
        await asyncio.wait_for(future, timeout=2.0)

        assert wf.status == WorkflowStatus.COMPLETED
        assert wf.tasks["r1"].status == TaskStatus.COMPLETED
        assert wf.tasks["r2"].status == TaskStatus.COMPLETED
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_recovery_from_postgres_state_store(postgres_pool):
    from db.postgres_state_store import PostgresStateStore

    bus = InMemoryEventBus()
    store = PostgresStateStore(postgres_pool)
    model = _make_model_stub("recovered result")

    # First coordinator saves workflow and publishes ready task.
    coord1 = WorkflowCoordinator(bus, store)
    wf = Workflow(
        workflow_id="wf-recover",
        trace_id="tr-1",
        user_input="recover me",
        tasks={
            "t1": Task("t1", "work", "worker", "do work"),
        },
    )
    await coord1.start_workflow(wf)

    # Simulate process restart: new bus, new coordinator, same store.
    bus2 = InMemoryEventBus()
    coord2 = WorkflowCoordinator(bus2, store)
    scheduler = Scheduler(
        bus2,
        {
            "worker": lambda event: asyncio.create_task(
                bus2.publish(
                    Event(
                        event_id="e-done",
                        event_type=EventType.AGENT_COMPLETED,
                        trace_id=event.trace_id,
                        workflow_id=event.workflow_id,
                        task_id=event.task_id,
                        source="worker",
                        payload={"result": "recovered result"},
                    )
                )
            ),
        },
    )
    bus2.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
    bus2.subscribe(EventType.AGENT_COMPLETED, coord2.handle_task_completed)
    bus2.subscribe(EventType.AGENT_FAILED, coord2.handle_task_failed)
    await bus2.start()

    try:
        # Reload workflow and re-publish ready tasks for anything that was
        # dispatched but not completed before the restart.
        loaded = await store.load_task_graph(wf.workflow_id)
        assert loaded is not None
        recovered_wf, _ = loaded
        assert recovered_wf.workflow_id == wf.workflow_id

        # Re-drive ready tasks that were lost in the old bus.
        await coord2._publish_ready_tasks(recovered_wf)

        future = asyncio.get_running_loop().create_future()
        coord2.set_completion_future(recovered_wf.workflow_id, future)
        await asyncio.wait_for(future, timeout=2.0)

        assert recovered_wf.status == WorkflowStatus.COMPLETED
        assert recovered_wf.tasks["t1"].status == TaskStatus.COMPLETED
        assert recovered_wf.tasks["t1"].result == "recovered result"
    finally:
        await bus2.stop()


@pytest.mark.asyncio
async def test_dispatched_task_re_published_after_recovery(postgres_pool):
    from db.postgres_state_store import PostgresStateStore

    bus = InMemoryEventBus()
    store = PostgresStateStore(postgres_pool)

    coord1 = WorkflowCoordinator(bus, store)
    wf = Workflow(
        workflow_id="wf-dispatched",
        trace_id="tr-1",
        user_input="recover dispatched",
        tasks={
            "t1": Task("t1", "work", "worker", "do work"),
        },
    )
    await coord1.start_workflow(wf)

    # At this point t1 is DISPATCHED in the store but the old bus is gone.
    loaded = await store.load_task_graph(wf.workflow_id)
    assert loaded is not None
    _, graph = loaded
    assert graph.tasks["t1"].status == TaskStatus.DISPATCHED

    # New process recovers and re-publishes ready tasks.
    bus2 = InMemoryEventBus()
    coord2 = WorkflowCoordinator(bus2, store)
    ready_events: list[Event] = []
    bus2.subscribe(EventType.TASK_READY, lambda e: ready_events.append(e))
    await bus2.start()

    try:
        loaded2 = await store.load_task_graph(wf.workflow_id)
        assert loaded2 is not None
        recovered_wf, _ = loaded2
        await coord2._publish_ready_tasks(recovered_wf)
        await asyncio.sleep(0.05)

        assert len(ready_events) == 1
        assert ready_events[0].task_id == "t1"
    finally:
        await bus2.stop()
