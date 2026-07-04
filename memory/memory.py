"""Public Memory facade used by loop.py and agent.py."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from .storage import JsonMemoryStore
from .summarizer import MemoryAgent
from .vector_store import QdrantConversationMemory
from .vector_worker import VectorMemoryWorker
from .worker import MemoryWorker


class Memory:
    """Structured preference memory with async AI extraction."""

    def __init__(
        self,
        path: str | Path | None = None,
        memory_agent: MemoryAgent | None = None,
        async_enabled: bool = True,
        vector_memory: QdrantConversationMemory | None = None,
    ) -> None:
        self._store = JsonMemoryStore(path)
        self._async_enabled = async_enabled
        self._worker = (
            MemoryWorker(self._store, memory_agent)
            if async_enabled
            else None
        )
        self._agent = memory_agent or MemoryAgent()
        self._vector_enabled = (
            os.environ.get("ENABLE_VECTOR_MEMORY", "true").lower() == "true"
        )
        if vector_memory is not None:
            self._vector_memory = vector_memory
        elif self._vector_enabled:
            self._vector_memory = QdrantConversationMemory()
        else:
            self._vector_memory = None
        self._vector_worker = (
            VectorMemoryWorker(self._vector_memory)
            if self._vector_enabled and self._vector_memory is not None
            else None
        )

    def create(self, key: str, value: Any) -> bool:
        return self._store.create(key, value)

    def retrieve(self, key: str) -> str | None:
        return self._store.retrieve(key)

    def update(self, key: str, value: Any) -> bool:
        return self._store.update(key, value)

    def delete(self, key: str) -> bool:
        return self._store.delete(key)

    def exists(self, key: str) -> bool:
        return self._store.exists(key)

    def list(self) -> list[str]:
        return self._store.list()

    def all(self) -> dict[str, str]:
        return self._store.all()

    def append(self, key: str, value: Any) -> bool:
        return self._store.append(key, value)

    def remove_item(self, key: str, value: Any) -> bool:
        return self._store.remove_item(key, value)

    def replace_item(self, key: str, old_value: Any, new_value: Any) -> bool:
        return self._store.replace_item(key, old_value, new_value)

    def remember(self, user_input: str) -> dict[str, str]:
        """Schedule AI memory extraction and return immediately."""
        if not user_input.strip():
            return {}

        if self._async_enabled and self._worker is not None:
            self._worker.submit(user_input)
            return {}

        operations = self._agent.summarize(user_input, self._store.all())
        from .operations import apply_operation

        for operation in operations:
            apply_operation(self._store, operation)
        return self._store.all()

    def search_conversations(self, user_input: str) -> list[dict[str, Any]]:
        """Search vector memory with the raw user input only."""
        if self._vector_memory is None:
            return []
        return self._vector_memory.search(user_input)

    def remember_conversation(self, user_input: str, response: str) -> None:
        """Store a complete turn in vector memory asynchronously."""
        if not user_input.strip() or not response.strip():
            return
        if self._vector_worker is not None:
            self._vector_worker.submit(user_input, response)
            return
        if self._vector_memory is not None:
            self._vector_memory.add_turn(user_input, response)

    def store(self, key: str, value: Any) -> None:
        """Compatibility method for older agent.py / loop.py contracts."""
        self._store.store(key, value)

    def shutdown(self, wait: bool = False) -> None:
        if self._worker is not None:
            self._worker.shutdown(wait=wait)
        if self._vector_worker is not None:
            self._vector_worker.shutdown(wait=wait)

    def wait_idle(self) -> None:
        if self._worker is not None:
            self._worker.wait_idle()
        if self._vector_worker is not None:
            self._vector_worker.wait_idle()
