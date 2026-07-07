"""SQLite storage for local Memory state."""

from __future__ import annotations

import hashlib
import json
import pickle
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_outbox (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dedupe_key TEXT UNIQUE,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit_log (
                    audit_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
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

    def append_audit(
        self, actor: str, action: str, target_id: str, payload: dict[str, Any]
    ) -> str:
        audit_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_audit_log (
                    audit_id, actor, action, target_id, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    actor,
                    action,
                    target_id,
                    json.dumps(payload, ensure_ascii=False),
                    self._now(),
                ),
            )
            conn.commit()
        return audit_id

    def enqueue_outbox(
        self,
        event_type: str,
        payload: dict[str, Any],
        dedupe_key: str | None = None,
    ) -> str | None:
        event_id = uuid.uuid4().hex
        now = self._now()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO memory_outbox (
                        event_id, event_type, payload_json, dedupe_key, status,
                        attempts, last_error, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type,
                        json.dumps(payload, ensure_ascii=False),
                        dedupe_key,
                        "pending",
                        0,
                        None,
                        now,
                        now,
                    ),
                )
                conn.commit()
            return event_id
        except sqlite3.IntegrityError:
            return None

    def list_outbox(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM memory_outbox"
        params = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "dedupe_key": row["dedupe_key"],
                "status": row["status"],
                "attempts": row["attempts"],
                "last_error": row["last_error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    @staticmethod
    def history_turn_dedupe_key(turn: object) -> str:
        raw = json.dumps(turn, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def counts(self) -> DebugCounts:
        with self._connect() as conn:
            kv_count = conn.execute("SELECT COUNT(*) FROM memory_kv").fetchone()[0]
            outbox_count = conn.execute("SELECT COUNT(*) FROM memory_outbox").fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM memory_audit_log").fetchone()[0]
        return DebugCounts(kv=kv_count, outbox=outbox_count, audit=audit_count)
