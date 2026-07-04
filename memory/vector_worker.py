"""Async worker for storing complete conversation turns in vector memory."""

from __future__ import annotations

import queue
import threading

from .vector_store import QdrantConversationMemory


class VectorMemoryWorker:
    """Store conversation turns in the background."""

    def __init__(self, vector_memory: QdrantConversationMemory) -> None:
        self._vector_memory = vector_memory
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._loop,
            name="vector-memory-worker",
            daemon=True,
        )
        self._thread.start()

    def submit(self, user_input: str, response: str) -> None:
        self._queue.put((user_input, response))

    def shutdown(self, wait: bool = False) -> None:
        self._queue.put(None)
        if wait:
            self._queue.join()
            self._thread.join()

    def wait_idle(self) -> None:
        self._queue.join()

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                user_input, response = item
                self._vector_memory.add_turn(user_input, response)
            finally:
                self._queue.task_done()
