"""SQLite storage for local Memory state."""

from __future__ import annotations

import json
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path

from memory.models import DebugCounts


class SQLiteMemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_kv (
                    key TEXT PRIMARY KEY,
                    value_json TEXT,
                    value_pickle BLOB,
                    value_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")

    @staticmethod
    def _encode(value: object) -> tuple[str | None, bytes | None, str]:
        try:
            return json.dumps(value, ensure_ascii=False), None, "json"
        except TypeError:
            return None, pickle.dumps(value), "pickle"

    @staticmethod
    def _decode(
        value_json: str | None, value_pickle: bytes | None, value_type: str
    ) -> object | None:
        if value_type == "json" and value_json is not None:
            return json.loads(value_json)
        if value_type == "pickle" and value_pickle is not None:
            return pickle.loads(value_pickle)
        return None

    def set_kv(self, key: str, value: object) -> None:
        value_json, value_pickle, value_type = self._encode(value)
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_kv (
                    key, value_json, value_pickle, value_type, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    value_pickle = excluded.value_pickle,
                    value_type = excluded.value_type,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, value_pickle, value_type, now, now),
            )
            conn.commit()

    def get_kv(self, key: str) -> object | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value_json, value_pickle, value_type
                FROM memory_kv
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._decode(row["value_json"], row["value_pickle"], row["value_type"])

    def counts(self) -> DebugCounts:
        with self._connect() as conn:
            kv_count = conn.execute("SELECT COUNT(*) FROM memory_kv").fetchone()[0]
        return DebugCounts(kv=kv_count)
