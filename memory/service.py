"""Memory facade used by the agent."""

from __future__ import annotations

from typing import Any

from memory.config import MemoryConfig
from memory.models import DebugCounts


class Memory:
    """Compatibility-first Memory implementation.

    Phase 1 keeps an in-process dictionary so existing callers can import
    the real class before SQLite is connected in Phase 2.
    """

    def __init__(self, config: dict[str, Any] | MemoryConfig | None = None):
        if isinstance(config, MemoryConfig):
            self.config = config
        else:
            self.config = MemoryConfig.from_env(config)
        self._store: dict[str, Any] = {}

    def store(self, key: str, value: object) -> None:
        self._store[key] = value

    def retrieve(self, key: str) -> object | None:
        return self._store.get(key)

    def debug_counts(self) -> DebugCounts:
        return DebugCounts(kv=len(self._store))
