"""Human-like output pacing for girlfriend mode."""

from __future__ import annotations

import os
import random
import sys
import time
from typing import TextIO


class HumanizedRenderer:
    """Write text with small pauses around natural punctuation."""

    PUNCTUATION = "，。！？；、,.!?;…"

    def __init__(self) -> None:
        self.enabled = os.environ.get("ENABLE_HUMAN_PAUSES", "true").lower() == "true"
        self.min_pause = self._env_float("HUMAN_PAUSE_MIN_SECONDS", 0.03)
        self.max_pause = self._env_float("HUMAN_PAUSE_MAX_SECONDS", 0.16)

    def write(
        self,
        text: str,
        *,
        emotional: bool = True,
        stream: TextIO | None = None,
    ) -> None:
        target = stream or sys.stdout
        if not self.enabled or not emotional:
            target.write(text)
            target.flush()
            return

        for char in text:
            target.write(char)
            target.flush()
            if char in self.PUNCTUATION:
                time.sleep(random.uniform(self.min_pause, self.max_pause))

    def _env_float(self, key: str, default: float) -> float:
        try:
            return float(os.environ.get(key, str(default)))
        except ValueError:
            return default
