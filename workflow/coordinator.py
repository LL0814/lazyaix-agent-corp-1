"""WorkflowCoordinator advances Task Graph state based on events."""

from __future__ import annotations

import asyncio
import uuid

from events.bus import EventBus
from events.outbox import OutboxStore
from events.schema import Event, EventType
from workflow.graph import TaskGraph
from workflow.state import TaskStatus, Workflow, WorkflowStatus
from workflow.state_store import StateStore


class WorkflowCoordinator:
    """Owns workflow state, publishes ready tasks, and resumes on completed/failed events."""

    def __init__(
        self,
        event_bus: EventBus,
        state_store: StateStore,
        max_retries: int = 2,
        outbox: OutboxStore | None = None,
    ):
        self.event_bus = event_bus
        self.state_store = state_store
        self.max_retries = max_retries
        self.outbox = outbox
        self._completions: dict[str, asyncio.Future] = {}

    def create_future(self, workflow_id: str) -> asyncio.Future:
        """Create a future that will be resolved when the identified workflow completes."""
        # workflow_id identifies which workflow this future is tied to.
        return asyncio.get_running_loop().create_future()

    def set_completion_future(
        self, workflow_id: str, future: asyncio.Future
    ) -> None:
        self._completions[workflow_id] = future

    async def start_workflow(self, workflow: Workflow) -> None:
        await self.state_store.save_workflow(workflow)
        graph = TaskGraph(workflow)
        graph.validate()
        workflow.status = WorkflowStatus.EXECUTING
        updated = await self.state_store.update_workflow_status(
            workflow.workflow_id, WorkflowStatus.EXECUTING, version=workflow.version
        )
        if updated:
            workflow.version += 1
        await self._publish_ready_tasks(workflow)

    async def handle_task_completed(self, event: Event) -> None:
        loaded = await self.state_store.load_task_graph(event.workflow_id)
        if loaded is None or event.task_id is None:
            return
        workflow, graph = loaded
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            return  # ignore events for already-terminal workflows

        task = workflow.tasks.get(event.task_id)
        if task is None:
            return
        if task.status == TaskStatus.COMPLETED:
            return  # idempotent

        graph.mark_completed(event.task_id, event.payload.get("result"))
        await self._publish_ready_tasks(workflow)
        await self._check_completion(workflow)
        await self.state_store.save_workflow(workflow)

    async def handle_task_failed(self, event: Event) -> None:
        loaded = await self.state_store.load_task_graph(event.workflow_id)
        if loaded is None or event.task_id is None:
            return
        workflow, graph = loaded
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            return  # ignore events for already-terminal workflows

        task = workflow.tasks.get(event.task_id)
        if task is None:
            return
        if task.status in (TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.COMPLETED):
            return
        if task.status == TaskStatus.RETRYING:
            # A retry has already been scheduled for this failure; ignore duplicate event.
            return

        retryable = event.payload.get("retryable", False)
        if retryable and task.retry_count < self.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.RETRYING
            await self._publish_event_for_task(task, workflow)
            await self.state_store.save_workflow(workflow)
            return

        graph.mark_failed(event.task_id, event.payload)
        self._block_downstream(workflow, event.task_id)
        await self._check_completion(workflow)
        await self.state_store.save_workflow(workflow)

    def _block_downstream(self, workflow: Workflow, failed_task_id: str) -> None:
        graph = TaskGraph(workflow)
        terminal = {TaskStatus.FAILED, TaskStatus.BLOCKED}
        changed = True
        while changed:
            changed = False
            for task in workflow.tasks.values():
                if task.status != TaskStatus.PENDING:
                    continue
                if any(
                    workflow.tasks[dep].status in terminal
                    for dep in task.dependencies
                ):
                    graph.mark_blocked(task.task_id)
                    changed = True

    async def _publish_ready_tasks(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        for task in graph.ready_tasks():
            graph.mark_ready(task.task_id)
            await self._publish_event_for_task(task, workflow)
        await self.state_store.save_workflow(workflow)

    async def _publish_event_for_task(self, task, workflow: Workflow) -> None:
        if task.status not in (TaskStatus.READY, TaskStatus.RETRYING):
            return
        task.status = TaskStatus.DISPATCHED
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.TASK_READY,
            trace_id=workflow.trace_id,
            workflow_id=workflow.workflow_id,
            task_id=task.task_id,
            source="coordinator",
            target_capability=task.target_capability,
            payload={
                "instructions": task.instructions,
                "input": task.input,
                "input_refs": task.input_refs,
            },
            metadata={"retry_count": task.retry_count},
        )
        if self.outbox is not None:
            await self.outbox.enqueue(
                event, topic="task.ready", key=event.task_id
            )
        else:
            await self.event_bus.publish(event)

    async def _check_completion(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        if graph.is_complete():
            workflow.status = WorkflowStatus.COMPLETED
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.WORKFLOW_COMPLETED,
                    trace_id=workflow.trace_id,
                    workflow_id=workflow.workflow_id,
                    source="coordinator",
                    payload={"workflow_id": workflow.workflow_id},
                )
            )
            self._resolve_completion_future(workflow.workflow_id)
        elif graph.has_failed_required():
            workflow.status = WorkflowStatus.FAILED
            failed_tasks = [
                {"task_id": t.task_id, "error": t.error}
                for t in workflow.tasks.values()
                if t.required_for_completion
                and t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
            ]
            workflow.error = {
                "message": "Required tasks failed or were blocked",
                "failed_tasks": failed_tasks,
            }
            await self.event_bus.publish(
                Event(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.WORKFLOW_FAILED,
                    trace_id=workflow.trace_id,
                    workflow_id=workflow.workflow_id,
                    source="coordinator",
                )
            )
            self._resolve_completion_future(workflow.workflow_id)
        elif not graph.ready_tasks():
            workflow.status = WorkflowStatus.WAITING
        await self.state_store.save_workflow(workflow)

    def _resolve_completion_future(self, workflow_id: str) -> None:
        future = self._completions.pop(workflow_id, None)
        if future is not None and not future.done():
            future.set_result(None)
