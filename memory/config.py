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
    extractor_provider: str = "rule"
    extractor_fallback_to_rule: bool = True
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    auto_process_outbox: bool = True

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "MemoryConfig":
        overrides = cls._normalize_overrides(overrides or {})
        deepseek_api_key = (
            os.getenv("MEMORY_DEEPSEEK_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("DS_API_KEY", "")
        )
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
            "extractor_provider": os.getenv("MEMORY_EXTRACTOR_PROVIDER", "rule"),
            "extractor_fallback_to_rule": _bool(os.getenv("MEMORY_EXTRACTOR_FALLBACK_TO_RULE"), True),
            "deepseek_api_key": deepseek_api_key,
            "deepseek_base_url": (
                os.getenv("MEMORY_DEEPSEEK_BASE_URL")
                or os.getenv("DEEPSEEK_BASE_URL")
                or os.getenv("DS_BASE_URL")
                or "https://api.deepseek.com"
            ),
            "deepseek_model": (
                os.getenv("MEMORY_DEEPSEEK_MODEL")
                or os.getenv("DEEPSEEK_MODEL")
                or "deepseek-v4-pro"
            ),
            "auto_process_outbox": _bool(os.getenv("MEMORY_AUTO_PROCESS_OUTBOX"), True),
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
            "MEMORY_EXTRACTOR_PROVIDER": "extractor_provider",
            "MEMORY_EXTRACTOR_FALLBACK_TO_RULE": "extractor_fallback_to_rule",
            "MEMORY_DEEPSEEK_API_KEY": "deepseek_api_key",
            "DEEPSEEK_API_KEY": "deepseek_api_key",
            "DS_API_KEY": "deepseek_api_key",
            "MEMORY_DEEPSEEK_BASE_URL": "deepseek_base_url",
            "DEEPSEEK_BASE_URL": "deepseek_base_url",
            "DS_BASE_URL": "deepseek_base_url",
            "MEMORY_DEEPSEEK_MODEL": "deepseek_model",
            "DEEPSEEK_MODEL": "deepseek_model",
            "MEMORY_AUTO_PROCESS_OUTBOX": "auto_process_outbox",
        }
        normalized: dict[str, Any] = {}
        for key, value in overrides.items():
            normalized[env_to_field.get(key, key)] = value
        return normalized
