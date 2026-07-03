import pytest

from workflow.graph import TaskGraph, TaskGraphError
from workflow.state import Task, TaskStatus, Workflow


def make_wf(*tasks: Task) -> Workflow:
    return Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="test",
        tasks={t.task_id: t for t in tasks},
    )


def test_ready_tasks_independent():
    t1 = Task("r1", "research", "researcher", "do research")
    t2 = Task("w1", "write", "writer", "write poem")
    graph = TaskGraph(make_wf(t1, t2))
    ready = graph.ready_tasks()
    assert {t.task_id for t in ready} == {"r1", "w1"}


def test_ready_tasks_with_dependency():
    r1 = Task("r1", "research", "researcher", "do research")
    w1 = Task("w1", "write", "writer", "write", dependencies=["r1"])
    graph = TaskGraph(make_wf(r1, w1))
    assert graph.ready_tasks() == [r1]
    graph.mark_completed("r1", "result")
    assert graph.ready_tasks() == [w1]


def test_unknown_dependency():
    t1 = Task("t1", "write", "writer", "x", dependencies=["missing"])
    graph = TaskGraph(make_wf(t1))
    with pytest.raises(TaskGraphError, match="unknown task"):
        graph.validate()


def test_duplicate_task_id():
    t1 = Task("t1", "write", "writer", "a")
    t2 = Task("t1", "research", "researcher", "b")
    wf = make_wf(t1)
    wf.tasks["t1-alt"] = t2
    graph = TaskGraph(wf)
    with pytest.raises(TaskGraphError, match="Duplicate"):
        graph.validate()


def test_cyclic_dependency():
    a = Task("a", "write", "writer", "a", dependencies=["b"])
    b = Task("b", "write", "writer", "b", dependencies=["a"])
    graph = TaskGraph(make_wf(a, b))
    with pytest.raises(TaskGraphError, match="Cycle"):
        graph.validate()


def test_is_complete():
    r1 = Task("r1", "research", "researcher", "r")
    w1 = Task("w1", "write", "writer", "w", dependencies=["r1"])
    graph = TaskGraph(make_wf(r1, w1))
    assert not graph.is_complete()
    graph.mark_completed("r1", "x")
    graph.mark_completed("w1", "y")
    assert graph.is_complete()
