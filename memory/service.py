"""Memory facade used by the agent."""

from __future__ import annotations

from typing import Any

from memory.audit import ACTION_KV_STORED, ACTION_OUTBOX_ENQUEUED, DEFAULT_ACTOR
from memory.backends.sqlite_store import SQLiteMemoryStore
from memory.config import MemoryConfig
from memory.models import DebugCounts


class Memory:
    """Compatibility-first Memory implementation.

    Uses SQLite by default for compatibility state, with an in-process
    dictionary available via MEMORY_BACKEND=memory for tests and fallback.
    """

    def __init__(self, config: dict[str, Any] | MemoryConfig | None = None):
        if isinstance(config, MemoryConfig):
            self.config = config
        else:
            self.config = MemoryConfig.from_env(config)
        self._store: dict[str, Any] = {}
        self._sqlite = (
            SQLiteMemoryStore(self.config.db_path)
            if self.config.backend == "sqlite"
            else None
        )

    def store(self, key: str, value: object) -> None:
        if self._sqlite is not None:
            self._sqlite.set_kv(key, value)
            self._sqlite.append_audit(DEFAULT_ACTOR, ACTION_KV_STORED, key, {"key": key})
            if key == "history" and self.config.generate_memories:
                self._enqueue_history_candidates(value)
        else:
            self._store[key] = value

    def retrieve(self, key: str) -> object | None:
        if self._sqlite is not None:
            return self._sqlite.get_kv(key)
        return self._store.get(key)

    def debug_counts(self) -> DebugCounts:
        if self._sqlite is not None:
            return self._sqlite.counts()
        return DebugCounts(kv=len(self._store))

    def _enqueue_history_candidates(self, value: object) -> None:
        if self._sqlite is None or not isinstance(value, list):
            return
        for turn in value:
            if not isinstance(turn, dict):
                continue
            text = f"Q: {turn.get('input', '')}\nA: {turn.get('response', '')}"
            dedupe_key = self._sqlite.history_turn_dedupe_key(turn)
            event_id = self._sqlite.enqueue_outbox(
                "memory.semantic_candidate.created",
                {
                    "text": text,
                    "key": "history",
                    "tenant_id": self.config.tenant_id,
                    "user_id": self.config.user_id,
                    "project_id": self.config.project_id,
                    "thread_id": self.config.thread_id,
                },
                dedupe_key=dedupe_key,
            )
            if event_id is not None:
                self._sqlite.append_audit(
                    DEFAULT_ACTOR,
                    ACTION_OUTBOX_ENQUEUED,
                    event_id,
                    {
                        "event_type": "memory.semantic_candidate.created",
                        "dedupe_key": dedupe_key,
                    },
                )
