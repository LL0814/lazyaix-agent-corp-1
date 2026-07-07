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

from memory.models import (
    DebugCounts,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    SourceRef,
)


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_sources (
                    source_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    thread_id TEXT,
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    importance REAL NOT NULL,
                    sensitivity TEXT NOT NULL,
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    summary_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    content TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, user_id, project_id, scope)
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

    def update_outbox_status(
        self,
        event_id: str,
        status: str,
        *,
        payload: dict[str, Any] | None = None,
        last_error: str | None = None,
        increment_attempts: bool = False,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json, attempts
                FROM memory_outbox
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return False
            payload_json = json.dumps(
                payload if payload is not None else json.loads(row["payload_json"]),
                ensure_ascii=False,
            )
            attempts = int(row["attempts"]) + 1 if increment_attempts else int(row["attempts"])
            cursor = conn.execute(
                """
                UPDATE memory_outbox
                SET status = ?, payload_json = ?, attempts = ?, last_error = ?, updated_at = ?
                WHERE event_id = ?
                """,
                (status, payload_json, attempts, last_error, self._now(), event_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def history_turn_dedupe_key(turn: object) -> str:
        raw = json.dumps(turn, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def insert_source(self, source: SourceRef) -> str:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_sources (
                    source_id, source_type, source_ref, excerpt, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.source_type,
                    source.source_ref,
                    source.excerpt,
                    json.dumps(source.metadata, ensure_ascii=False),
                    source.created_at.isoformat(),
                ),
            )
            conn.commit()
        return source.source_id

    def insert_record(self, record: MemoryRecord) -> str:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records (
                    memory_id, tenant_id, user_id, project_id, thread_id, scope,
                    kind, content, metadata_json, status, confidence, importance,
                    sensitivity, source_id, created_at, updated_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.tenant_id,
                    record.user_id,
                    record.project_id,
                    record.thread_id,
                    record.scope.value,
                    record.kind.value,
                    record.content,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.status.value,
                    record.confidence,
                    record.importance,
                    record.sensitivity,
                    record.source_id,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.expires_at.isoformat() if record.expires_at else None,
                ),
            )
            conn.commit()
        return record.memory_id

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        row = self._fetch_record_row(memory_id)
        return self._record_from_row(row) if row is not None else None

    def list_records(self, memory_ids: list[str]) -> list[MemoryRecord]:
        return [
            record
            for memory_id in memory_ids
            if (record := self.get_record(memory_id)) is not None
        ]

    def mark_deleted(self, memory_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_records
                SET status = ?, updated_at = ?
                WHERE memory_id = ? AND status != ?
                """,
                (
                    MemoryStatus.DELETED.value,
                    self._now(),
                    memory_id,
                    MemoryStatus.DELETED.value,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def upsert_summary(
        self,
        tenant_id: str,
        user_id: str,
        project_id: str,
        scope: str,
        content: str,
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_summaries (
                    summary_id, tenant_id, user_id, project_id, scope, content,
                    version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, user_id, project_id, scope)
                DO UPDATE SET
                    content = excluded.content,
                    version = memory_summaries.version + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    uuid.uuid4().hex,
                    tenant_id,
                    user_id,
                    project_id,
                    scope,
                    content,
                    1,
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_summary(
        self,
        tenant_id: str,
        user_id: str,
        project_id: str,
        scope: str,
    ) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content
                FROM memory_summaries
                WHERE tenant_id = ? AND user_id = ? AND project_id = ? AND scope = ?
                """,
                (tenant_id, user_id, project_id, scope),
            ).fetchone()
        return str(row["content"]) if row is not None else ""

    def list_active_records(self) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_records
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (MemoryStatus.ACTIVE.value,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def _fetch_record_row(self, memory_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM memory_records WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

    def _record_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            thread_id=row["thread_id"],
            scope=MemoryScope(row["scope"]),
            kind=MemoryKind(row["kind"]),
            content=row["content"],
            metadata=json.loads(row["metadata_json"]),
            status=MemoryStatus(row["status"]),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            sensitivity=row["sensitivity"],
            source_id=row["source_id"],
            created_at=self._parse_datetime(row["created_at"]) or datetime.utcnow(),
            updated_at=self._parse_datetime(row["updated_at"]) or datetime.utcnow(),
            expires_at=self._parse_datetime(row["expires_at"]),
        )

    def counts(self) -> DebugCounts:
        with self._connect() as conn:
            kv_count = conn.execute("SELECT COUNT(*) FROM memory_kv").fetchone()[0]
            outbox_count = conn.execute("SELECT COUNT(*) FROM memory_outbox").fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM memory_audit_log").fetchone()[0]
            records_count = conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0]
            sources_count = conn.execute("SELECT COUNT(*) FROM memory_sources").fetchone()[0]
            summaries_count = conn.execute("SELECT COUNT(*) FROM memory_summaries").fetchone()[0]
        return DebugCounts(
            kv=kv_count,
            records=records_count,
            sources=sources_count,
            outbox=outbox_count,
            audit=audit_count,
            summaries=summaries_count,
        )
