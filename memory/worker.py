"""Outbox worker for turning memory candidates into durable memories."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memory.audit import DEFAULT_ACTOR
from memory.models import MemoryClassification, MemoryKind
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

            text = self._candidate_text(payload)
            if not text:
                self._mark_skipped(event_id, payload, "候选文本为空", result)
                return

            redacted = redact_text(text)
            classifications = self._extract_classifications(redacted.text)
            if not classifications:
                self._mark_skipped(
                    event_id,
                    {
                        **payload,
                        "worker_result": {
                            "should_remember": False,
                            "redacted": redacted.redacted,
                            "redaction_markers": redacted.markers,
                            "reason": "抽取器没有返回候选记忆",
                        },
                    },
                    "抽取器没有返回候选记忆",
                    result,
                )
                return

            extracted_at = self._now()
            processed_items: list[dict[str, Any]] = []
            remembered_ids: list[str] = []
            for classification in classifications:
                item = self._process_classification(
                    event_id=event_id,
                    payload=payload,
                    redacted_text=redacted.text,
                    redacted=redacted.redacted,
                    redaction_markers=redacted.markers,
                    classification=classification,
                    extracted_at=extracted_at,
                    source_event_created_at=str(row["created_at"]),
                )
                processed_items.append(item)
                if item.get("memory_id"):
                    remembered_ids.append(str(item["memory_id"]))

            remembered_items = [item for item in processed_items if item["should_remember"]]
            if not remembered_items:
                self._mark_skipped(
                    event_id,
                    {
                        **payload,
                        "worker_result": {
                            "should_remember": False,
                            "processed_items": len(processed_items),
                            "items": processed_items,
                            "redacted": redacted.redacted,
                            "redaction_markers": redacted.markers,
                            "reason": "没有值得写入的记忆",
                        },
                    },
                    "没有值得写入的记忆",
                    result,
                )
                return

            primary = remembered_items[0]
            worker_result = {
                "should_remember": True,
                "processed_items": len(processed_items),
                "items": processed_items,
                "redacted": redacted.redacted,
                "redaction_markers": redacted.markers,
                "kind": primary["kind"],
                "confidence": primary["confidence"],
                "importance": primary["importance"],
                "reason": primary["reason"],
                "content": primary["content"],
            }
            if primary.get("memory_id"):
                worker_result["memory_id"] = primary["memory_id"]

            processed_payload = {
                **payload,
                "worker_result": worker_result,
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
                {
                    "memory_ids": remembered_ids,
                    "kinds": [item["kind"] for item in remembered_items],
                },
            )
            result["processed"] += 1
            result["remembered_ids"].extend(remembered_ids)
        except Exception as exc:
            self._mark_failed(event_id, payload, str(exc), result)

    def _extract_classifications(self, text: str) -> list[MemoryClassification]:
        extract_many = getattr(self.memory._candidate_extractor, "extract_many", None)
        if callable(extract_many):
            return list(extract_many(text))
        return [self.memory._candidate_extractor.extract(text)]

    @staticmethod
    def _candidate_text(payload: dict[str, Any]) -> str:
        user_input = str(payload.get("input", "")).strip()
        if user_input:
            return user_input
        return str(payload.get("text", "")).strip()

    def _process_classification(
        self,
        *,
        event_id: str,
        payload: dict[str, Any],
        redacted_text: str,
        redacted: bool,
        redaction_markers: list[str],
        classification: MemoryClassification,
        extracted_at: str,
        source_event_created_at: str,
    ) -> dict[str, Any]:
        memory_content = classification.content or redacted_text
        item: dict[str, Any] = {
            "should_remember": classification.should_remember,
            "kind": classification.kind.value,
            "confidence": classification.confidence,
            "importance": classification.importance,
            "reason": classification.reason,
            "content": memory_content,
            "observed_at": classification.observed_at,
            "extracted_at": extracted_at,
            "source_event_created_at": source_event_created_at,
            "redacted": redacted,
            "redaction_markers": redaction_markers,
        }
        if not classification.should_remember:
            return item

        if classification.kind == MemoryKind.SUMMARY:
            self.memory.update_summary(memory_content)
            item["summary_updated"] = True
            return item

        memory_id = self.memory.remember(
            memory_content,
            kind=classification.kind.value,
            metadata={
                "outbox_event_id": event_id,
                "source_event_id": event_id,
                "source_event_created_at": source_event_created_at,
                "extracted_at": extracted_at,
                "observed_at": classification.observed_at,
                "extractor_provider": self.memory.config.extractor_provider,
                "extractor_model": self.memory.config.deepseek_model,
                "classification": classification.model_dump(mode="json"),
            },
            source={
                "source_type": "outbox",
                "source_ref": event_id,
                "outbox_payload": payload,
            },
            confidence=classification.confidence,
            importance=classification.importance,
        )
        item["memory_id"] = memory_id
        return item

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")

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
