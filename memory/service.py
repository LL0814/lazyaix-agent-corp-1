"""Memory facade used by the agent."""

from __future__ import annotations

from typing import Any

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
