"""Memory facade used by the agent."""

from __future__ import annotations

import uuid
import re
from typing import Any

from memory.audit import (
    ACTION_KV_STORED,
    ACTION_MEMORY_FORGOTTEN,
    ACTION_OUTBOX_ENQUEUED,
    DEFAULT_ACTOR,
)
from memory.backends.qdrant_store import QdrantMemoryIndex
from memory.backends.sqlite_store import SQLiteMemoryStore
from memory.config import MemoryConfig
from memory.embeddings import create_embedding_provider
from memory.exporter import export_jsonl, export_markdown, parse_jsonl
from memory.extractors import MemoryCandidateExtractor, create_memory_candidate_extractor
from memory.models import (
    DebugCounts,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    MemoryStatus,
    RedactionResult,
    SourceRef,
)
from memory.redaction import redact_text
from memory.retrieval import combined_score
from memory.worker import MemoryOutboxWorker


class Memory:
    """Compatibility-first Memory implementation.

    Uses SQLite by default for compatibility state, with an in-process
    dictionary available via MEMORY_BACKEND=memory for tests and fallback.
    """

    def __init__(
        self,
        config: dict[str, Any] | MemoryConfig | None = None,
        embedding_provider: Any | None = None,
        vector_index: Any | None = None,
        candidate_extractor: MemoryCandidateExtractor | None = None,
    ):
        if isinstance(config, MemoryConfig):
            self.config = config
        else:
            self.config = MemoryConfig.from_env(config)
        self._store: dict[str, Any] = {}
        self._sqlite = (
            SQLiteMemoryStore(self.config.db_path)
            if self.config.backend == "sqlite"
            else None
        )
        self._embedding_provider = embedding_provider or create_embedding_provider(self.config)
        self._vector_index = vector_index or QdrantMemoryIndex(
            url=self.config.qdrant_url,
            collection_name=self.config.qdrant_collection,
            vector_size=self.config.embedding_dimension,
        )
        self._candidate_extractor = candidate_extractor or create_memory_candidate_extractor(
            self.config
        )

    def store(self, key: str, value: object) -> None:
        if self._sqlite is not None:
            self._sqlite.set_kv(key, value)
            self._sqlite.append_audit(DEFAULT_ACTOR, ACTION_KV_STORED, key, {"key": key})
            if key == "history" and self.config.generate_memories:
                self._enqueue_history_candidates(value)
        else:
            self._store[key] = value

    def retrieve(self, key: str) -> object | None:
        if self._sqlite is not None:
            return self._sqlite.get_kv(key)
        return self._store.get(key)

    def debug_counts(self) -> DebugCounts:
        if self._sqlite is not None:
            return self._sqlite.counts()
        return DebugCounts(kv=len(self._store))

    def remember(
        self,
        content: str,
        *,
        kind: str = "semantic",
        scope: str = "project",
        metadata: dict[str, Any] | None = None,
        source: dict[str, Any] | None = None,
        confidence: float = 1.0,
        importance: float = 0.5,
    ) -> str:
        if self._sqlite is None:
            raise RuntimeError("Semantic memory requires the sqlite backend.")

        metadata = metadata or {}
        source = source or {}
        redacted = (
            redact_text(content)
            if self.config.redact_secrets
            else RedactionResult(text=content)
        )
        memory_id = f"mem_{uuid.uuid4().hex}"
        source_ref = SourceRef(
            source_id=f"src_{uuid.uuid4().hex}",
            source_type=str(source.get("source_type", "manual")),
            source_ref=str(source.get("source_ref", "")),
            excerpt=redacted.text[:500],
            metadata=source,
        )
        record = MemoryRecord(
            memory_id=memory_id,
            tenant_id=self.config.tenant_id,
            user_id=self.config.user_id,
            project_id=self.config.project_id,
            thread_id=self.config.thread_id,
            scope=MemoryScope(scope),
            kind=MemoryKind(kind),
            content=redacted.text,
            metadata=metadata,
            confidence=confidence,
            importance=importance,
            source_id=source_ref.source_id,
        )
        vector = self._embedding_provider.embed(redacted.text)
        self._vector_index.upsert_memory(record, vector)
        self._sqlite.insert_source(source_ref)
        self._sqlite.insert_record(record)
        self._sqlite.append_audit(
            DEFAULT_ACTOR,
            "memory.record.remembered",
            memory_id,
            {"kind": kind, "scope": scope},
        )
        return memory_id

    def process_outbox(self, *, limit: int = 10) -> dict[str, Any]:
        return MemoryOutboxWorker(self).process_pending(limit=limit)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: str | None = None,
        project_id: str | None = None,
        include_sources: bool = True,
    ) -> list[MemorySearchResult]:
        if not self.config.use_memories or self._sqlite is None:
            return []

        vector = self._embedding_provider.embed(query)
        filters = {
            "tenant_id": self.config.tenant_id,
            "user_id": self.config.user_id,
            "project_id": project_id or self.config.project_id,
            "status": MemoryStatus.ACTIVE.value,
        }
        if scope is not None:
            filters["scope"] = scope
        hits = self._vector_index.search(vector, filters, top_k)
        records = self._sqlite.list_records([str(hit["memory_id"]) for hit in hits])
        record_by_id = {
            record.memory_id: record
            for record in records
            if record.status == MemoryStatus.ACTIVE and not self._is_search_noise(record)
        }
        results: list[MemorySearchResult] = []
        for hit in hits:
            record = record_by_id.get(str(hit["memory_id"]))
            if record is None:
                continue
            results.append(
                MemorySearchResult(
                    memory_id=record.memory_id,
                    content=record.content,
                    kind=record.kind,
                    scope=record.scope,
                    score=combined_score(float(hit["score"]), record),
                    source=None if include_sources else None,
                    metadata=record.metadata,
                )
            )
        seen_ids = {result.memory_id for result in results}
        for record in self._sqlite.search_records_by_terms(
            self._query_terms(query),
            tenant_id=self.config.tenant_id,
            user_id=self.config.user_id,
            project_id=project_id or self.config.project_id,
            scope=scope,
            limit=top_k,
        ):
            if record.memory_id in seen_ids or self._is_search_noise(record):
                continue
            results.append(
                MemorySearchResult(
                    memory_id=record.memory_id,
                    content=record.content,
                    kind=record.kind,
                    scope=record.scope,
                    score=combined_score(0.7, record),
                    source=None,
                    metadata=record.metadata,
                )
            )
            seen_ids.add(record.memory_id)
        return sorted(results, key=lambda result: result.score, reverse=True)

    def forget(self, memory_id: str, *, reason: str = "") -> bool:
        if self._sqlite is None:
            return False
        changed = self._sqlite.mark_deleted(memory_id)
        if changed:
            self._vector_index.delete_memory(memory_id)
            self._sqlite.append_audit(
                DEFAULT_ACTOR,
                ACTION_MEMORY_FORGOTTEN,
                memory_id,
                {"reason": reason},
            )
        return changed

    def get_summary(self, *, scope: str = "project") -> str:
        if self._sqlite is None:
            return ""
        return self._sqlite.get_summary(
            self.config.tenant_id,
            self.config.user_id,
            self.config.project_id,
            scope,
        )

    def update_summary(self, summary: str, *, scope: str = "project") -> None:
        if self._sqlite is None:
            raise RuntimeError("Summary memory requires the sqlite backend.")
        self._sqlite.upsert_summary(
            self.config.tenant_id,
            self.config.user_id,
            self.config.project_id,
            scope,
            summary,
        )

    def export(self, format: str = "markdown") -> str:
        if self._sqlite is None:
            return ""
        records = self._sqlite.list_active_records()
        if format == "markdown":
            return export_markdown(self.get_summary(), records)
        if format == "jsonl":
            return export_jsonl(records)
        raise ValueError(f"Unsupported export format: {format}")

    def import_memories(self, content: str, *, source: str = "manual") -> list[str]:
        created_ids: list[str] = []
        if content.lstrip().startswith("{"):
            for row in parse_jsonl(content):
                created_ids.append(
                    self.remember(
                        str(row["content"]),
                        kind=str(row.get("kind", "semantic")),
                        scope=str(row.get("scope", "project")),
                        metadata=dict(row.get("metadata", {})),
                        source={"source_type": source},
                    )
                )
            return created_ids

        for line in content.splitlines():
            if not line.startswith("- "):
                continue
            item = line[2:].strip()
            if item.startswith("[") and "] " in item:
                item = item.split("] ", 1)[1]
            created_ids.append(
                self.remember(item, source={"source_type": source})
            )
        if not created_ids:
            raise ValueError("No importable memories found")
        return created_ids

    def _enqueue_history_candidates(self, value: object) -> None:
        if self._sqlite is None or not isinstance(value, list):
            return
        for turn in value:
            if not isinstance(turn, dict):
                continue
            text = f"Q: {turn.get('input', '')}\nA: {turn.get('response', '')}"
            dedupe_key = self._sqlite.history_turn_dedupe_key(turn)
            event_id = self._sqlite.enqueue_outbox(
                "memory.semantic_candidate.created",
                {
                    "text": text,
                    "input": turn.get("input", ""),
                    "response": turn.get("response", ""),
                    "key": "history",
                    "tenant_id": self.config.tenant_id,
                    "user_id": self.config.user_id,
                    "project_id": self.config.project_id,
                    "thread_id": self.config.thread_id,
                },
                dedupe_key=dedupe_key,
            )
            if event_id is not None:
                self._sqlite.append_audit(
                    DEFAULT_ACTOR,
                    ACTION_OUTBOX_ENQUEUED,
                    event_id,
                    {
                        "event_type": "memory.semantic_candidate.created",
                        "dedupe_key": dedupe_key,
                    },
                )

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        text = query.strip()
        replacements = (
            "长期记忆",
            "分别",
            "有哪些",
            "有什么",
            "什么",
            "偏好",
            "流程",
            "习惯",
            "基于",
            "方面",
            "说说",
            "我的",
            "我在",
            "你",
            "和",
        )
        for word in replacements:
            text = text.replace(word, " ")
        raw_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_+-]{2,}", text)
        expansions = {
            "会议": ["会议", "周会", "排会"],
            "住宿": ["住宿", "酒店"],
            "合同": ["合同", "续费", "自动扣款"],
            "招聘": ["招聘", "候选人"],
        }
        terms: list[str] = []
        for term in raw_terms:
            terms.extend(expansions.get(term, [term]))
        deduped: list[str] = []
        for term in terms:
            if term not in deduped:
                deduped.append(term)
        return deduped

    @staticmethod
    def _is_search_noise(record: MemoryRecord) -> bool:
        content = record.content.strip()
        return content.startswith("Q:") and (
            "长期记忆" in content
            or "还记得" in content
            or "API Key 配置异常" in content
            or "模型调用失败" in content
        )
