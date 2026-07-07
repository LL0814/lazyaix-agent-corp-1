"""Workflow and Task state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorkflowStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    task_id: str
    task_type: str
    target_capability: str
    instructions: str
    input: dict | None = None
    dependencies: list[str] = field(default_factory=list)
    input_refs: list[str] = field(default_factory=list)
    required_for_completion: bool = True
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: dict | None = None
    retry_count: int = 0
    version: int = 1
    parent_task_id: str | None = None
    target_agent: str | None = None
    max_retries: int = 2
    priority: str = "normal"


@dataclass
class Workflow:
    workflow_id: str
    trace_id: str
    user_input: str
    tasks: dict[str, Task] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.CREATED
    final_result: str | None = None
    error: dict | None = None
    version: int = 1
    parent_workflow_id: str | None = None
