"""Memory layer data models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryScope(StrEnum):
    GLOBAL = "global"
    USER = "user"
    PROJECT = "project"
    THREAD = "thread"


class MemoryKind(StrEnum):
    KV_STATE = "kv_state"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    SUMMARY = "summary"
    TOMBSTONE = "tombstone"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    EXPIRED = "expired"


class SourceRef(BaseModel):
    source_id: str
    source_type: str = "manual"
    source_ref: str = ""
    excerpt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class MemoryRecord(BaseModel):
    memory_id: str
    tenant_id: str
    user_id: str
    project_id: str
    thread_id: str | None = None
    scope: MemoryScope = MemoryScope.PROJECT
    kind: MemoryKind = MemoryKind.SEMANTIC
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: MemoryStatus = MemoryStatus.ACTIVE
    confidence: float = 1.0
    importance: float = 0.5
    sensitivity: str = "normal"
    source_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime | None = None


class MemorySearchResult(BaseModel):
    memory_id: str
    content: str
    kind: MemoryKind
    scope: MemoryScope
    score: float
    source: SourceRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DebugCounts(BaseModel):
    kv: int = 0
    records: int = 0
    sources: int = 0
    outbox: int = 0
    audit: int = 0
    summaries: int = 0
