"""Background worker for non-blocking memory updates."""

from __future__ import annotations

import queue
import threading

from .operations import MemoryOperation, apply_operation
from .storage import JsonMemoryStore
from .summarizer import MemoryAgent


class MemoryWorker:
    """Run AI memory summarization without blocking the main conversation."""

    def __init__(
        self,
        store: JsonMemoryStore,
        agent: MemoryAgent | None = None,
    ) -> None:
        self._store = store
        self._agent = agent or MemoryAgent()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._loop,
            name="memory-worker",
            daemon=True,
        )
        self._thread.start()

    def submit(self, user_input: str) -> None:
        self._queue.put(user_input)

    def shutdown(self, wait: bool = False) -> None:
        self._queue.put(None)
        if wait:
            self._queue.join()
            self._thread.join()

    def wait_idle(self) -> None:
        self._queue.join()

    def _loop(self) -> None:
        while True:
            user_input = self._queue.get()
            try:
                if user_input is None:
                    return
                self._run(user_input)
            finally:
                self._queue.task_done()

    def _run(self, user_input: str) -> list[MemoryOperation]:
        operations = self._agent.summarize(user_input, self._store.all())
        for operation in operations:
            apply_operation(self._store, operation)
        return operations
