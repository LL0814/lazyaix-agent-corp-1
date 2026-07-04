"""Proactive message scheduler for girlfriend mode."""

from __future__ import annotations

import os
import queue
import random
import threading

from .engine import GirlfriendEngine


class ProactiveScheduler:
    """Emit proactive girlfriend messages at irregular intervals."""

    def __init__(
        self,
        engine: GirlfriendEngine,
        output_queue: queue.Queue[str],
    ) -> None:
        self.engine = engine
        self.output_queue = output_queue
        self.min_seconds = self._env_int("GIRLFRIEND_PROACTIVE_MIN_SECONDS", 180)
        self.max_seconds = self._env_int("GIRLFRIEND_PROACTIVE_MAX_SECONDS", 7200)
        self.continuous_min_seconds = self._env_int(
            "GIRLFRIEND_CONTINUOUS_MIN_SECONDS",
            30,
        )
        self.continuous_max_seconds = self._env_int(
            "GIRLFRIEND_CONTINUOUS_MAX_SECONDS",
            120,
        )
        self.burst_chance = self._env_float("GIRLFRIEND_PROACTIVE_BURST_CHANCE", 0.35)
        self.burst_max = self._env_int("GIRLFRIEND_PROACTIVE_BURST_MAX", 3)
        if self.max_seconds < self.min_seconds:
            self.max_seconds = self.min_seconds
        if self.continuous_max_seconds < self.continuous_min_seconds:
            self.continuous_max_seconds = self.continuous_min_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="girlfriend-proactive-scheduler",
            daemon=True,
        )

    def start(self) -> None:
        if self.enabled():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def enabled(self) -> bool:
        return os.environ.get("ENABLE_GIRLFRIEND_MODE", "true").lower() == "true"

    def _loop(self) -> None:
        while not self._stop.is_set():
            wait_seconds = self._next_wait_seconds()
            if self._stop.wait(wait_seconds):
                return
            self._emit_message_burst()

    def _continuous_enabled(self) -> bool:
        return os.environ.get("GIRLFRIEND_CONTINUOUS_CHAT", "true").lower() == "true"

    def _next_wait_seconds(self) -> float:
        state = self.engine.store.get_state()
        if state.get("relationship_status") == "crisis":
            crisis_min = self._env_int("GIRLFRIEND_CRISIS_PROACTIVE_MIN_SECONDS", 3)
            crisis_max = self._env_int("GIRLFRIEND_CRISIS_PROACTIVE_MAX_SECONDS", 20)
            return random.uniform(crisis_min, max(crisis_min, crisis_max))

        if not self._continuous_enabled():
            return random.uniform(self.min_seconds, self.max_seconds)

        mood = int(state.get("mood", 0))
        jealousy = int(state.get("jealousy", 0))
        if mood < -30 or jealousy > 40:
            return random.uniform(15, max(45, self.continuous_min_seconds))
        return random.uniform(self.continuous_min_seconds, self.continuous_max_seconds)

    def _emit_message_burst(self) -> None:
        count = 1
        if random.random() < self.burst_chance:
            count = random.randint(2, max(2, self.burst_max))

        for index in range(count):
            message = self.engine.generate_proactive_message()
            if message:
                self.output_queue.put(message)
            if index < count - 1:
                pause = random.uniform(3, 12)
                if self._stop.wait(pause):
                    return

    def _env_int(self, key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default

    def _env_float(self, key: str, default: float) -> float:
        try:
            return float(os.environ.get(key, str(default)))
        except ValueError:
            return default
