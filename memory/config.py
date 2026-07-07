"""Configuration for the Memory layer."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class MemoryConfig(BaseModel):
    enable_memory: bool = True
    use_memories: bool = True
    generate_memories: bool = True
    disable_on_external_context: bool = True
    redact_secrets: bool = True
    backend: str = "sqlite"
    tenant_id: str = "local"
    user_id: str = "default"
    project_id: str = "lazyaiX-agent-corp-1"
    thread_id: str | None = None
    db_path: str = ".memory/memory.sqlite3"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "agent_memories_v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "MemoryConfig":
        overrides = cls._normalize_overrides(overrides or {})
        data = {
            "enable_memory": _bool(os.getenv("ENABLE_MEMORY"), True),
            "use_memories": _bool(os.getenv("MEMORY_USE_MEMORIES"), True),
            "generate_memories": _bool(os.getenv("MEMORY_GENERATE_MEMORIES"), True),
            "disable_on_external_context": _bool(os.getenv("MEMORY_DISABLE_ON_EXTERNAL_CONTEXT"), True),
            "redact_secrets": _bool(os.getenv("MEMORY_REDACT_SECRETS"), True),
            "backend": os.getenv("MEMORY_BACKEND", "sqlite"),
            "tenant_id": os.getenv("MEMORY_TENANT_ID", "local"),
            "user_id": os.getenv("MEMORY_USER_ID", "default"),
            "project_id": os.getenv("MEMORY_PROJECT_ID", "lazyaiX-agent-corp-1"),
            "thread_id": os.getenv("MEMORY_THREAD_ID") or None,
            "db_path": os.getenv("MEMORY_DB_PATH", ".memory/memory.sqlite3"),
            "qdrant_url": os.getenv("QDRANT_URL", "http://localhost:6333"),
            "qdrant_collection": os.getenv("QDRANT_COLLECTION", "agent_memories_v1"),
            "embedding_model": os.getenv("MEMORY_EMBEDDING_MODEL", "BAAI/bge-m3"),
            "embedding_dimension": int(os.getenv("MEMORY_EMBEDDING_DIMENSION", "1024")),
        }
        data.update(overrides)
        return cls(**data)

    @staticmethod
    def _normalize_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
        env_to_field = {
            "ENABLE_MEMORY": "enable_memory",
            "MEMORY_USE_MEMORIES": "use_memories",
            "MEMORY_GENERATE_MEMORIES": "generate_memories",
            "MEMORY_DISABLE_ON_EXTERNAL_CONTEXT": "disable_on_external_context",
            "MEMORY_REDACT_SECRETS": "redact_secrets",
            "MEMORY_BACKEND": "backend",
            "MEMORY_TENANT_ID": "tenant_id",
            "MEMORY_USER_ID": "user_id",
            "MEMORY_PROJECT_ID": "project_id",
            "MEMORY_THREAD_ID": "thread_id",
            "MEMORY_DB_PATH": "db_path",
            "QDRANT_URL": "qdrant_url",
            "QDRANT_COLLECTION": "qdrant_collection",
            "MEMORY_EMBEDDING_MODEL": "embedding_model",
            "MEMORY_EMBEDDING_DIMENSION": "embedding_dimension",
        }
        normalized: dict[str, Any] = {}
        for key, value in overrides.items():
            normalized[env_to_field.get(key, key)] = value
        return normalized
