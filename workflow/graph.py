"""Task Graph validation and state advancement."""

from __future__ import annotations

from workflow.state import Task, TaskStatus, Workflow


class TaskGraphError(Exception):
    """Raised when a Task Graph is invalid."""


class TaskGraph:
    """Manages a DAG of Tasks inside a Workflow."""

    def __init__(self, workflow: Workflow):
        self.workflow = workflow

    def validate(self) -> None:
        """Validate the task graph. Raises TaskGraphError on problems."""
        tasks = self.workflow.tasks
        seen_ids = set()
        for task in tasks.values():
            if task.task_id in seen_ids:
                raise TaskGraphError(f"Duplicate task_id: {task.task_id}")
            seen_ids.add(task.task_id)

        for task in tasks.values():
            for dep in task.dependencies:
                if dep not in tasks:
                    raise TaskGraphError(
                        f"Task {task.task_id} depends on unknown task {dep}"
                    )

        # Cycle detection using DFS.
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in tasks}
        stack: list[str] = []

        def dfs(tid: str) -> None:
            color[tid] = GRAY
            stack.append(tid)
            for dep in tasks[tid].dependencies:
                if color[dep] == GRAY:
                    cycle = " -> ".join(stack[stack.index(dep):] + [dep])
                    raise TaskGraphError(f"Cycle detected: {cycle}")
                if color[dep] == WHITE:
                    dfs(dep)
            stack.pop()
            color[tid] = BLACK

        for tid in tasks:
            if color[tid] == WHITE:
                dfs(tid)

    def ready_tasks(self) -> list[Task]:
        """Return tasks whose dependencies are all completed."""
        ready: list[Task] = []
        for task in self.workflow.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_satisfied = all(
                self.workflow.tasks[dep].status == TaskStatus.COMPLETED
                for dep in task.dependencies
            )
            if deps_satisfied:
                ready.append(task)
        return ready

    def mark_ready(self, task_id: str) -> None:
        task = self.workflow.tasks[task_id]
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.READY

    def mark_dispatched(self, task_id: str) -> None:
        task = self.workflow.tasks[task_id]
        if task.status == TaskStatus.READY:
            task.status = TaskStatus.DISPATCHED

    def mark_completed(self, task_id: str, result) -> None:
        task = self.workflow.tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.error = None

    def mark_failed(self, task_id: str, error: dict) -> None:
        task = self.workflow.tasks[task_id]
        task.status = TaskStatus.FAILED
        task.error = error

    def mark_blocked(self, task_id: str) -> None:
        task = self.workflow.tasks[task_id]
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.BLOCKED

    def is_complete(self) -> bool:
        """True when all required tasks are completed."""
        return all(
            task.status == TaskStatus.COMPLETED
            for task in self.workflow.tasks.values()
            if task.required_for_completion
        )

    def has_failed_required(self) -> bool:
        """True when any required task is failed or blocked (terminal failure)."""
        return any(
            task.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
            for task in self.workflow.tasks.values()
            if task.required_for_completion
        )
