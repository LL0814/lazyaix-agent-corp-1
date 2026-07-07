import uuid

import pytest

from db.postgres_state_store import PostgresStateStore
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


def make_wf(*tasks):
    return Workflow(
        workflow_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


@pytest.mark.asyncio
async def test_postgres_save_and_get_workflow(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    got = await store.get_workflow(wf.workflow_id)
    assert got is not None
    assert got.workflow_id == wf.workflow_id
    assert got.trace_id == wf.trace_id
    assert got.user_input == "test"
    assert len(got.tasks) == 1
    assert "t1" in got.tasks


@pytest.mark.asyncio
async def test_postgres_optimistic_lock(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    ok = await store.update_workflow_status(wf.workflow_id, WorkflowStatus.EXECUTING, version=99)
    assert ok is False


@pytest.mark.asyncio
async def test_postgres_dependencies_round_trip(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    t1 = Task("t1", "work", "worker", "do work")
    t2 = Task("t2", "work", "worker", "do more", dependencies=["t1"])
    wf = make_wf(t1, t2)
    await store.save_workflow(wf)

    got = await store.get_workflow(wf.workflow_id)
    assert got is not None
    assert got.tasks["t2"].dependencies == ["t1"]

    loaded = await store.load_task_graph(wf.workflow_id)
    assert loaded is not None
    _, graph = loaded
    ready = graph.ready_tasks()
    assert len(ready) == 1
    assert ready[0].task_id == "t1"


@pytest.mark.asyncio
async def test_postgres_update_task_status(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)

    ok = await store.update_task_status("t1", TaskStatus.COMPLETED, result={"output": "ok"}, version=1)
    assert ok is True

    task = await store.get_task("t1")
    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"output": "ok"}
    assert task.version == 2


@pytest.mark.asyncio
async def test_postgres_save_task_raises_for_orphan(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    orphan = Task("orphan", "work", "worker", "no workflow")
    with pytest.raises(RuntimeError, match="Cannot save orphan task"):
        await store.save_task(orphan)


@pytest.mark.asyncio
async def test_postgres_task_status_optimistic_lock(postgres_pool):
    store = PostgresStateStore(postgres_pool)
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)

    ok = await store.update_task_status("t1", TaskStatus.RUNNING, version=99)
    assert ok is False
