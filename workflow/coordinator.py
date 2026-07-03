"""WorkflowCoordinator advances Task Graph state based on events."""

from __future__ import annotations

import asyncio
import uuid

from events.bus import EventBus
from events.schema import Event, EventType
from workflow.graph import TaskGraph
from workflow.state import TaskStatus, Workflow, WorkflowStatus


class WorkflowCoordinator:
    """Owns workflow state, publishes ready tasks, and resumes on completed/failed events."""

    def __init__(
        self,
        event_bus: EventBus,
        max_retries: int = 2,
    ):
        self.event_bus = event_bus
        self.max_retries = max_retries
        self._workflows: dict[str, Workflow] = {}
        self._completions: dict[str, asyncio.Future] = {}

    def register(self, workflow: Workflow) -> None:
        self._workflows[workflow.workflow_id] = workflow

    def create_future(self, workflow_id: str) -> asyncio.Future:
        """Create a future that will be resolved when the identified workflow completes."""
        # workflow_id identifies which workflow this future is tied to.
        return asyncio.get_event_loop().create_future()

    def set_completion_future(
        self, workflow_id: str, future: asyncio.Future
    ) -> None:
        self._completions[workflow_id] = future

    async def start_workflow(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        graph.validate()
        workflow.status = WorkflowStatus.EXECUTING
        self.register(workflow)
        await self._publish_ready_tasks(workflow)

    async def handle_task_completed(self, event: Event) -> None:
        workflow = self._workflows.get(event.workflow_id)
        if workflow is None or event.task_id is None:
            return
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            return  # ignore events for already-terminal workflows
        graph = TaskGraph(workflow)

        task = workflow.tasks.get(event.task_id)
        if task is None:
            return
        if task.status == TaskStatus.COMPLETED:
            return  # idempotent

        graph.mark_completed(event.task_id, event.payload.get("result"))
        await self._publish_ready_tasks(workflow)
        await self._check_completion(workflow)

    async def handle_task_failed(self, event: Event) -> None:
        workflow = self._workflows.get(event.workflow_id)
        if workflow is None or event.task_id is None:
            return
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            return  # ignore events for already-terminal workflows
        graph = TaskGraph(workflow)

        task = workflow.tasks.get(event.task_id)
        if task is None:
            return

        retryable = event.payload.get("retryable", False)
        if retryable and task.retry_count < self.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.RETRYING
            await self._publish_event_for_task(task, workflow)
            return

        graph.mark_failed(event.task_id, event.payload)
        self._block_downstream(workflow, event.task_id)
        await self._check_completion(workflow)

    def _block_downstream(self, workflow: Workflow, failed_task_id: str) -> None:
        graph = TaskGraph(workflow)
        for task in workflow.tasks.values():
            if failed_task_id in task.dependencies and task.status == TaskStatus.PENDING:
                graph.mark_blocked(task.task_id)

    async def _publish_ready_tasks(self, workflow: Workflow) -> None:
        graph = TaskGraph(workflow)
        for task in graph.ready_tasks():
            graph.mark_ready(task.task_id)
            await self._publish_event_for_task(task, workflow)

    async def _publish_event_for_task(self, task, workflow: Workflow) -> None:
        if task.status not in (TaskStatus.READY, TaskStatus.RETRYING):
            return
        task.status = TaskStatus.DISPATCHED
        await self.event_bus.publish(
            Event(
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
        )

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

    def _resolve_completion_future(self, workflow_id: str) -> None:
        future = self._completions.pop(workflow_id, None)
        if future is not None and not future.done():
            future.set_result(None)
