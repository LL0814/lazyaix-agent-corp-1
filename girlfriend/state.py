"""SQLite state store for the AI girlfriend layer."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GirlfriendStateStore:
    """Persist relationship state and recent events in a local SQLite DB."""

    DEFAULTS = {
        "mood": "0",
        "affection": "20",
        "trust": "20",
        "jealousy": "0",
        "personality": "strong",
        "negative_intensity": "medium",
        "relationship_status": "normal",
        "crisis_topic": "",
        "last_interaction_at": "",
        "last_proactive_at": "",
    }

    def __init__(self, path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parent / "girlfriend.db"
        self.path = Path(path or os.environ.get("GIRLFRIEND_DB_PATH") or default_path)
        self.mood_min = self._env_int("GIRLFRIEND_MOOD_MIN", -100)
        self.mood_max = self._env_int("GIRLFRIEND_MOOD_MAX", 100)
        self._lock = threading.Lock()
        self._ensure_db()

    def _env_int(self, key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    delta_mood INTEGER NOT NULL DEFAULT 0,
                    delta_affection INTEGER NOT NULL DEFAULT 0,
                    delta_trust INTEGER NOT NULL DEFAULT 0,
                    delta_jealousy INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL
                )
                """
            )
            for key, value in self.DEFAULTS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO state (key, value) VALUES (?, ?)",
                    (key, value),
                )

    def get_state(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM state").fetchall()
        data = {row["key"]: row["value"] for row in rows}
        return {
            "mood": self._to_int(data.get("mood"), 0),
            "affection": self._to_int(data.get("affection"), 20),
            "trust": self._to_int(data.get("trust"), 20),
            "jealousy": self._to_int(data.get("jealousy"), 0),
            "personality": data.get("personality", "strong"),
            "negative_intensity": os.environ.get(
                "GIRLFRIEND_NEGATIVE_INTENSITY",
                data.get("negative_intensity", "medium"),
            ),
            "relationship_status": data.get("relationship_status", "normal"),
            "crisis_topic": data.get("crisis_topic", ""),
            "last_interaction_at": data.get("last_interaction_at", ""),
            "last_proactive_at": data.get("last_proactive_at", ""),
        }

    def update_scores(
        self,
        *,
        mood: int = 0,
        affection: int = 0,
        trust: int = 0,
        jealousy: int = 0,
        kind: str = "interaction",
        summary: str = "",
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            current = self._read_state_unlocked(conn)
            next_values = {
                "mood": self._clamp(current["mood"] + mood),
                "affection": self._clamp(current["affection"] + affection),
                "trust": self._clamp(current["trust"] + trust),
                "jealousy": self._clamp(current["jealousy"] + jealousy),
            }
            for key, value in next_values.items():
                conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                    (key, str(value)),
                )
            if any((mood, affection, trust, jealousy)) or summary:
                conn.execute(
                    """
                    INSERT INTO events (
                        created_at, kind, delta_mood, delta_affection,
                        delta_trust, delta_jealousy, summary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (utc_now(), kind, mood, affection, trust, jealousy, summary),
                )
        return self.get_state()

    def set_value(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                (key, str(value)),
            )

    def record_interaction(self) -> None:
        self.set_value("last_interaction_at", utc_now())

    def record_proactive(self) -> None:
        self.set_value("last_proactive_at", utc_now())

    def recent_events(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, kind, delta_mood, delta_affection,
                       delta_trust, delta_jealousy, summary
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _read_state_unlocked(self, conn: sqlite3.Connection) -> dict[str, int]:
        rows = conn.execute("SELECT key, value FROM state").fetchall()
        data = {row["key"]: row["value"] for row in rows}
        return {
            "mood": self._to_int(data.get("mood"), 0),
            "affection": self._to_int(data.get("affection"), 20),
            "trust": self._to_int(data.get("trust"), 20),
            "jealousy": self._to_int(data.get("jealousy"), 0),
        }

    def _to_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _clamp(self, value: int) -> int:
        return max(self.mood_min, min(self.mood_max, value))
