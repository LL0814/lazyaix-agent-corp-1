"""StateStore abstraction and in-process implementation."""

from __future__ import annotations

from typing import Any, Protocol

from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


class StateStore(Protocol):
    async def save_workflow(self, workflow: Workflow) -> None: ...
    async def get_workflow(self, workflow_id: str) -> Workflow | None: ...
    async def update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, *, version: int
    ) -> bool: ...

    async def save_task(self, task: Task) -> None: ...
    async def get_task(self, task_id: str) -> Task | None: ...
    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Any = None,
        error: dict | None = None,
        version: int = 1,
    ) -> bool: ...

    async def list_ready_tasks(self, workflow_id: str) -> list[Task]: ...
    async def load_task_graph(self, workflow_id: str) -> tuple[Workflow, TaskGraph] | None: ...


class InMemoryStateStore:
    """Process-local StateStore used for unit tests and single-process deployments."""

    def __init__(self):
        self._workflows: dict[str, Workflow] = {}
        self._tasks: dict[str, Task] = {}
        self._versions: dict[str, int] = {}

    async def save_workflow(self, workflow: Workflow) -> None:
        self._workflows[workflow.workflow_id] = workflow
        for task in workflow.tasks.values():
            self._tasks[task.task_id] = task
        self._versions.setdefault(f"wf:{workflow.workflow_id}", 1)

    async def get_workflow(self, workflow_id: str) -> Workflow | None:
        return self._workflows.get(workflow_id)

    async def update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, *, version: int
    ) -> bool:
        key = f"wf:{workflow_id}"
        if self._versions.get(key) != version:
            return False
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return False
        wf.status = status
        wf.version = version + 1
        self._versions[key] = version + 1
        return True

    async def save_task(self, task: Task) -> None:
        self._tasks[task.task_id] = task
        self._versions.setdefault(f"task:{task.task_id}", 1)

    async def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Any = None,
        error: dict | None = None,
        version: int = 1,
    ) -> bool:
        key = f"task:{task_id}"
        if self._versions.get(key) != version:
            return False
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        task.version = version + 1
        self._versions[key] = version + 1
        return True

    async def list_ready_tasks(self, workflow_id: str) -> list[Task]:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return []
        from workflow.graph import TaskGraph

        graph = TaskGraph(wf)
        return graph.ready_tasks()

    async def load_task_graph(self, workflow_id: str) -> tuple[Workflow, TaskGraph] | None:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return None
        from workflow.graph import TaskGraph

        return wf, TaskGraph(wf)
