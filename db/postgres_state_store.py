"""PostgreSQL-backed StateStore implementation."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from workflow.graph import TaskGraph
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


def _task_to_row(task: Task, workflow_id: str) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "workflow_id": workflow_id,
        "parent_task_id": task.parent_task_id,
        "task_type": task.task_type,
        "target_capability": task.target_capability,
        "target_agent": task.target_agent,
        "instructions": task.instructions,
        "input": json.dumps(task.input) if task.input is not None else None,
        "input_refs": json.dumps(task.input_refs) if task.input_refs else None,
        "required_for_completion": task.required_for_completion,
        "status": task.status.value,
        "result": json.dumps(task.result) if task.result is not None else None,
        "error_info": json.dumps(task.error) if task.error is not None else None,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "priority": task.priority,
        "version": task.version,
    }


def _row_to_task(row: asyncpg.Record) -> Task:
    return Task(
        task_id=str(row["task_id"]),
        task_type=row["task_type"],
        target_capability=row["target_capability"],
        target_agent=row["target_agent"],
        instructions=row["instructions"],
        input=json.loads(row["input"]) if row["input"] else None,
        input_refs=json.loads(row["input_refs"]) if row["input_refs"] else [],
        required_for_completion=row["required_for_completion"],
        status=TaskStatus(row["status"]),
        result=json.loads(row["result"]) if row["result"] else None,
        error=json.loads(row["error_info"]) if row["error_info"] else None,
        retry_count=row["retry_count"],
        max_retries=row["max_retries"],
        priority=row["priority"],
        version=row["version"],
        parent_task_id=str(row["parent_task_id"]) if row["parent_task_id"] else None,
    )


def _row_to_workflow(row: asyncpg.Record, tasks: dict[str, Task]) -> Workflow:
    return Workflow(
        workflow_id=str(row["workflow_id"]),
        trace_id=str(row["trace_id"]),
        parent_workflow_id=str(row["parent_workflow_id"]) if row["parent_workflow_id"] else None,
        user_input=row["user_input"],
        status=WorkflowStatus(row["status"]),
        final_result=row["final_result"],
        error=json.loads(row["error_info"]) if row["error_info"] else None,
        tasks=tasks,
        version=row["version"],
    )


class PostgresStateStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save_workflow(self, workflow: Workflow) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO workflows (workflow_id, trace_id, parent_workflow_id, user_input, status, final_result, error_info, version)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (workflow_id) DO UPDATE SET
                        trace_id = EXCLUDED.trace_id,
                        parent_workflow_id = EXCLUDED.parent_workflow_id,
                        user_input = EXCLUDED.user_input,
                        status = EXCLUDED.status,
                        final_result = EXCLUDED.final_result,
                        error_info = EXCLUDED.error_info,
                        updated_at = NOW(),
                        version = EXCLUDED.version
                    """,
                    workflow.workflow_id,
                    workflow.trace_id,
                    workflow.parent_workflow_id,
                    workflow.user_input,
                    workflow.status.value,
                    workflow.final_result,
                    json.dumps(workflow.error) if workflow.error else None,
                    workflow.version,
                )
                for task in workflow.tasks.values():
                    await self._upsert_task(conn, task, workflow.workflow_id)

                # Delete tasks that are no longer part of this workflow.
                task_ids = list(workflow.tasks.keys())
                if task_ids:
                    await conn.execute(
                        """
                        DELETE FROM tasks
                        WHERE workflow_id = $1
                          AND task_id NOT IN (SELECT unnest($2::uuid[]))
                        """,
                        workflow.workflow_id,
                        task_ids,
                    )
                else:
                    await conn.execute(
                        "DELETE FROM tasks WHERE workflow_id = $1",
                        workflow.workflow_id,
                    )

                await conn.execute(
                    "DELETE FROM task_dependencies WHERE workflow_id = $1",
                    workflow.workflow_id,
                )
                for task in workflow.tasks.values():
                    await self._save_task_dependencies(conn, task, workflow.workflow_id)

    async def _upsert_task(self, conn: asyncpg.Connection, task: Task, workflow_id: str) -> None:
        row = _task_to_row(task, workflow_id)
        await conn.execute(
            """
            INSERT INTO tasks (
                task_id, workflow_id, parent_task_id, task_type, target_capability, target_agent,
                instructions, input, input_refs, required_for_completion, status,
                result, error_info, retry_count, max_retries, priority, version
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            ON CONFLICT (task_id) DO UPDATE SET
                workflow_id = EXCLUDED.workflow_id,
                parent_task_id = EXCLUDED.parent_task_id,
                task_type = EXCLUDED.task_type,
                target_capability = EXCLUDED.target_capability,
                target_agent = EXCLUDED.target_agent,
                instructions = EXCLUDED.instructions,
                input = EXCLUDED.input,
                input_refs = EXCLUDED.input_refs,
                required_for_completion = EXCLUDED.required_for_completion,
                status = EXCLUDED.status,
                result = EXCLUDED.result,
                error_info = EXCLUDED.error_info,
                retry_count = EXCLUDED.retry_count,
                max_retries = EXCLUDED.max_retries,
                priority = EXCLUDED.priority,
                updated_at = NOW(),
                version = EXCLUDED.version
            """,
            *[row[k] for k in [
                "task_id", "workflow_id", "parent_task_id", "task_type", "target_capability", "target_agent",
                "instructions", "input", "input_refs", "required_for_completion", "status",
                "result", "error_info", "retry_count", "max_retries", "priority", "version"
            ]]
        )

    async def _save_task_dependencies(
        self, conn: asyncpg.Connection, task: Task, workflow_id: str
    ) -> None:
        await conn.execute(
            "DELETE FROM task_dependencies WHERE workflow_id = $1 AND task_id = $2",
            workflow_id,
            task.task_id,
        )
        for dep in task.dependencies:
            await conn.execute(
                """
                INSERT INTO task_dependencies (workflow_id, task_id, depends_on_task_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                workflow_id,
                task.task_id,
                dep,
            )

    async def get_workflow(self, workflow_id: str) -> Workflow | None:
        async with self._pool.acquire() as conn:
            wf_row = await conn.fetchrow(
                "SELECT * FROM workflows WHERE workflow_id = $1", workflow_id
            )
            if wf_row is None:
                return None
            task_rows = await conn.fetch(
                "SELECT * FROM tasks WHERE workflow_id = $1", workflow_id
            )
            tasks = {str(row["task_id"]): _row_to_task(row) for row in task_rows}
            dep_rows = await conn.fetch(
                "SELECT task_id, depends_on_task_id FROM task_dependencies WHERE workflow_id = $1",
                workflow_id,
            )
            for row in dep_rows:
                task_id = str(row["task_id"])
                dep_id = str(row["depends_on_task_id"])
                if task_id in tasks:
                    tasks[task_id].dependencies.append(dep_id)
            return _row_to_workflow(wf_row, tasks)

    async def update_workflow_status(
        self, workflow_id: str, status: WorkflowStatus, *, version: int
    ) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE workflows
                SET status = $1, updated_at = NOW(), version = version + 1,
                    completed_at = CASE WHEN $1 IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE completed_at END
                WHERE workflow_id = $2 AND version = $3
                """,
                status.value,
                workflow_id,
                version,
            )
            return result == "UPDATE 1"

    async def save_task(self, task: Task) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT workflow_id FROM tasks WHERE task_id = $1", task.task_id)
                workflow_id = row["workflow_id"] if row else None
                if workflow_id is None:
                    raise RuntimeError(f"Cannot save orphan task {task.task_id} without workflow_id")
                await self._upsert_task(conn, task, workflow_id)
                await self._save_task_dependencies(conn, task, workflow_id)

    async def get_task(self, task_id: str) -> Task | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
            if row is None:
                return None
            task = _row_to_task(row)
            dep_rows = await conn.fetch(
                "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = $1",
                task_id,
            )
            task.dependencies = [str(r["depends_on_task_id"]) for r in dep_rows]
            return task

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: Any = None,
        error: dict | None = None,
        version: int = 1,
    ) -> bool:
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE tasks
                SET status = $1,
                    result = COALESCE($2, result),
                    error_info = COALESCE($3, error_info),
                    updated_at = NOW(),
                    version = version + 1,
                    started_at = CASE WHEN $1 = 'running' AND started_at IS NULL THEN NOW() ELSE started_at END,
                    completed_at = CASE WHEN $1 IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE completed_at END
                WHERE task_id = $4 AND version = $5
                """,
                status.value,
                json.dumps(result) if result is not None else None,
                json.dumps(error) if error is not None else None,
                task_id,
                version,
            )
            return res == "UPDATE 1"

    async def list_ready_tasks(self, workflow_id: str) -> list[Task]:
        loaded = await self.load_task_graph(workflow_id)
        if loaded is None:
            return []
        _, graph = loaded
        return graph.ready_tasks()

    async def load_task_graph(self, workflow_id: str) -> tuple[Workflow, TaskGraph] | None:
        wf = await self.get_workflow(workflow_id)
        if wf is None:
            return None
        return wf, TaskGraph(wf)
