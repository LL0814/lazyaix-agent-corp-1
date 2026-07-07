"""Outbox worker for turning memory candidates into durable memories."""

from __future__ import annotations

from typing import Any

from memory.audit import DEFAULT_ACTOR
from memory.classifier import classify_memory_candidate
from memory.redaction import redact_text


class MemoryOutboxWorker:
    def __init__(self, memory: Any):
        self.memory = memory

    def process_pending(self, limit: int = 10) -> dict[str, Any]:
        if self.memory._sqlite is None:
            return {"processed": 0, "skipped": 0, "failed": 0, "remembered_ids": []}

        result: dict[str, Any] = {
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "remembered_ids": [],
        }
        rows = self.memory._sqlite.list_outbox(status="pending")[:limit]
        for row in rows:
            self._process_row(row, result)
        return result

    def _process_row(self, row: dict[str, Any], result: dict[str, Any]) -> None:
        event_id = str(row["event_id"])
        payload = dict(row["payload"])
        try:
            if row["event_type"] != "memory.semantic_candidate.created":
                self._mark_skipped(event_id, payload, "不支持的 outbox 事件类型", result)
                return

            text = str(payload.get("text", "")).strip()
            if not text:
                self._mark_skipped(event_id, payload, "候选文本为空", result)
                return

            redacted = redact_text(text)
            classification = classify_memory_candidate(redacted.text)
            if not classification.should_remember:
                self._mark_skipped(
                    event_id,
                    {
                        **payload,
                        "worker_result": {
                            "should_remember": False,
                            "kind": classification.kind.value,
                            "confidence": classification.confidence,
                            "importance": classification.importance,
                            "reason": classification.reason,
                            "redacted": redacted.redacted,
                            "redaction_markers": redacted.markers,
                        },
                    },
                    classification.reason,
                    result,
                )
                return

            memory_id = self.memory.remember(
                redacted.text,
                kind=classification.kind.value,
                metadata={
                    "outbox_event_id": event_id,
                    "classification": classification.model_dump(mode="json"),
                },
                source={
                    "source_type": "outbox",
                    "source_ref": event_id,
                    "outbox_payload": payload,
                },
            )
            processed_payload = {
                **payload,
                "worker_result": {
                    "memory_id": memory_id,
                    "should_remember": True,
                    "kind": classification.kind.value,
                    "confidence": classification.confidence,
                    "importance": classification.importance,
                    "reason": classification.reason,
                    "redacted": redacted.redacted,
                    "redaction_markers": redacted.markers,
                },
            }
            self.memory._sqlite.update_outbox_status(
                event_id,
                "processed",
                payload=processed_payload,
                last_error=None,
                increment_attempts=True,
            )
            self.memory._sqlite.append_audit(
                DEFAULT_ACTOR,
                "memory.outbox.processed",
                event_id,
                {"memory_id": memory_id, "kind": classification.kind.value},
            )
            result["processed"] += 1
            result["remembered_ids"].append(memory_id)
        except Exception as exc:
            self._mark_failed(event_id, payload, str(exc), result)

    def _mark_skipped(
        self,
        event_id: str,
        payload: dict[str, Any],
        reason: str,
        result: dict[str, Any],
    ) -> None:
        payload.setdefault(
            "worker_result",
            {
                "should_remember": False,
                "reason": reason,
            },
        )
        self.memory._sqlite.update_outbox_status(
            event_id,
            "skipped",
            payload=payload,
            last_error=None,
            increment_attempts=True,
        )
        self.memory._sqlite.append_audit(
            DEFAULT_ACTOR,
            "memory.outbox.skipped",
            event_id,
            {"reason": reason},
        )
        result["skipped"] += 1

    def _mark_failed(
        self,
        event_id: str,
        payload: dict[str, Any],
        error: str,
        result: dict[str, Any],
    ) -> None:
        payload["worker_result"] = {"error": error}
        self.memory._sqlite.update_outbox_status(
            event_id,
            "failed",
            payload=payload,
            last_error=error,
            increment_attempts=True,
        )
        self.memory._sqlite.append_audit(
            DEFAULT_ACTOR,
            "memory.outbox.failed",
            event_id,
            {"error": error},
        )
        result["failed"] += 1
