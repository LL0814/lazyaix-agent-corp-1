import pytest

from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus
from workflow.state_store import InMemoryStateStore


def make_wf(*tasks):
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


@pytest.mark.asyncio
async def test_save_and_get_workflow():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    got = await store.get_workflow("wf-1")
    assert got is not None
    assert got.workflow_id == "wf-1"
    assert got.status == WorkflowStatus.CREATED


@pytest.mark.asyncio
async def test_update_workflow_status():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    ok = await store.update_workflow_status("wf-1", WorkflowStatus.EXECUTING, version=1)
    assert ok is True
    got = await store.get_workflow("wf-1")
    assert got.status == WorkflowStatus.EXECUTING


@pytest.mark.asyncio
async def test_update_workflow_status_optimistic_lock_failure():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    ok = await store.update_workflow_status("wf-1", WorkflowStatus.EXECUTING, version=99)
    assert ok is False


@pytest.mark.asyncio
async def test_save_and_get_task():
    store = InMemoryStateStore()
    task = Task("t1", "work", "worker", "do work")
    await store.save_task(task)
    got = await store.get_task("t1")
    assert got is task


@pytest.mark.asyncio
async def test_update_task_status():
    store = InMemoryStateStore()
    task = Task("t1", "work", "worker", "do work")
    await store.save_task(task)
    ok = await store.update_task_status(
        "t1", TaskStatus.COMPLETED, result="done", version=1
    )
    assert ok is True
    got = await store.get_task("t1")
    assert got.status == TaskStatus.COMPLETED
    assert got.result == "done"
    assert got.version == 2


@pytest.mark.asyncio
async def test_update_task_status_optimistic_lock_failure():
    store = InMemoryStateStore()
    task = Task("t1", "work", "worker", "do work")
    await store.save_task(task)
    ok = await store.update_task_status("t1", TaskStatus.COMPLETED, version=99)
    assert ok is False


@pytest.mark.asyncio
async def test_list_ready_tasks():
    store = InMemoryStateStore()
    t1 = Task("t1", "work", "worker", "do work")
    t2 = Task("t2", "work", "worker", "do more", dependencies=["t1"])
    wf = make_wf(t1, t2)
    await store.save_workflow(wf)
    ready = await store.list_ready_tasks("wf-1")
    assert ready == [t1]


@pytest.mark.asyncio
async def test_load_task_graph():
    store = InMemoryStateStore()
    wf = make_wf(Task("t1", "work", "worker", "do work"))
    await store.save_workflow(wf)
    loaded = await store.load_task_graph("wf-1")
    assert loaded is not None
    got_wf, graph = loaded
    assert got_wf.workflow_id == "wf-1"
    assert graph.workflow is got_wf
