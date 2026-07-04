"""Event data model and event type constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class EventType:
    TASK_CREATED = "task.created"
    TASK_READY = "task.ready"
    TASK_ASSIGNED = "task.assigned"
    TASK_RETRYING = "task.retrying"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    WORKFLOW_RESUME = "workflow.resume"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"


@dataclass
class Event:
    event_id: str
    event_type: str
    trace_id: str
    workflow_id: str
    task_id: str | None = None
    parent_task_id: str | None = None
    source: str = "supervisor"
    target_agent: str | None = None
    target_capability: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
