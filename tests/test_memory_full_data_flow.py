from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent import Agent
from context import Context
from memory import Memory
from memory.backends.qdrant_store import QdrantMemoryIndex
from memory.backends.sqlite_store import SQLiteMemoryStore
from memory.classifier import classify_memory_candidate
from memory.embeddings import BGEM3EmbeddingProvider, FakeEmbeddingProvider
from memory.models import MemoryKind, MemoryRecord, MemoryScope, MemoryStatus, SourceRef
from memory.redaction import redact_text


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def emit_flow(name: str, steps: list[dict[str, Any]]) -> None:
    print(f"\nDATA_FLOW::{name}")
    for index, step in enumerate(steps, start=1):
        payload = {"step": index, **_jsonable(step)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


class FakeIndex:
    def __init__(self):
        self.points: dict[str, dict[str, Any]] = {}
        self.deleted: set[str] = set()

    def upsert_memory(self, record, vector):
        self.points[record.memory_id] = {"record": record, "vector": vector}

    def search(self, vector, filters, top_k):
        results = []
        for memory_id, item in self.points.items():
            record = item["record"]
            if memory_id in self.deleted:
                continue
            if record.tenant_id != filters.get("tenant_id"):
                continue
            if record.user_id != filters.get("user_id"):
                continue
            if record.project_id != filters.get("project_id"):
                continue
            if record.status.value != filters.get("status"):
                continue
            if filters.get("scope") is not None and record.scope.value != filters["scope"]:
                continue
            results.append({"memory_id": memory_id, "score": 0.9})
        return results[:top_k]

    def delete_memory(self, memory_id):
        self.deleted.add(memory_id)


class FakeQdrantClient:
    def __init__(self):
        self.collections = {}
        self.points = {}
        self.deleted = []

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, vectors_config):
        self.collections[collection_name] = vectors_config

    def upsert(self, collection_name, points):
        self.points.setdefault(collection_name, {})
        for point in points:
            self.points[collection_name][point.id] = point

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        class Result:
            def __init__(self, points):
                self.points = points

        class Point:
            def __init__(self, point_id, payload):
                self.id = point_id
                self.payload = payload
                self.score = 0.9

        points = [
            Point(point.id, point.payload)
            for point in self.points.get(collection_name, {}).values()
        ][:limit]
        return Result(points)

    def delete(self, collection_name, points_selector):
        self.deleted.append((collection_name, points_selector))


def make_memory(tmp_path: Path, *, generate_memories: bool = True) -> Memory:
    return Memory(
        config={
            "MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3"),
            "MEMORY_GENERATE_MEMORIES": generate_memories,
        },
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
    )


def make_record(memory_id: str = "mem_flow") -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        tenant_id="local",
        user_id="default",
        project_id="lazyaiX-agent-corp-1",
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        content="用户喜欢安静酒店",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_kv_state_store_retrieve_debug_counts_data_flow(tmp_path: Path):
    memory = make_memory(tmp_path, generate_memories=False)
    requirement = {"destination": "成都", "days": 3, "budget": 3000}

    before = memory.debug_counts()
    memory.store("current_requirement", requirement)
    restored = Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
    )
    retrieved = restored.retrieve("current_requirement")
    after = restored.debug_counts()

    emit_flow(
        "kv_state.store_retrieve_debug_counts",
        [
            {"from": "Python dict", "to": "Memory.store('current_requirement')", "data": requirement},
            {"from": "Memory.store", "to": "SQLite memory_kv", "stored_as": "JSON"},
            {"from": "Memory.store", "to": "SQLite memory_audit_log", "action": "memory.kv.stored"},
            {"from": "SQLite memory_kv", "to": "Memory.retrieve", "data": retrieved},
            {"from": "SQLite tables", "to": "Memory.debug_counts", "before": before, "after": after},
        ],
    )

    assert retrieved == requirement
    assert after.kv == 1
    assert after.audit == 1


def test_history_outbox_to_candidate_to_record_data_flow(tmp_path: Path):
    memory = make_memory(tmp_path)
    history_turn = {
        "input": "以后每完成一步都写中文阶段报告并等待确认",
        "response": "收到",
    }

    memory.store("history", [history_turn])
    pending_event = memory._sqlite.list_outbox()[0]
    result = memory.process_outbox(limit=10)
    event = memory._sqlite.list_outbox()[0]
    candidate_text = event["payload"]["text"]
    worker_result = event["payload"]["worker_result"]
    memory_id = worker_result["memory_id"]
    record = memory._sqlite.get_record(memory_id)

    emit_flow(
        "history.outbox.automatic_worker_consumption",
        [
            {"from": "Agent/history turn", "to": "Memory.store('history')", "data": history_turn},
            {"from": "Memory.store('history')", "to": "SQLite memory_kv", "key": "history"},
            {
                "from": "Memory.store('history')",
                "to": "SQLite memory_outbox",
                "event_type": pending_event["event_type"],
                "status": pending_event["status"],
                "payload_text": candidate_text,
            },
            {
                "from": "memory_outbox.pending",
                "to": "Memory.process_outbox -> redact_text -> classify_memory_candidate",
                "worker_result": worker_result,
                "process_result": result,
            },
            {
                "from": "MemoryOutboxWorker",
                "to": "SQLite memory_records + Fake Qdrant index",
                "record": record,
                "vector_point_exists": memory_id in memory._vector_index.points,
            },
            {
                "from": "memory_outbox.pending",
                "to": "memory_outbox.processed",
                "status": event["status"],
            },
        ],
    )

    assert event["event_type"] == "memory.semantic_candidate.created"
    assert event["status"] == "processed"
    assert result["processed"] == 1
    assert worker_result["should_remember"] is True
    assert worker_result["kind"] == MemoryKind.PROCEDURAL.value
    assert record is not None
    assert record.kind == MemoryKind.PROCEDURAL
    assert memory_id in memory._vector_index.points


def test_durable_memory_kinds_search_forget_data_flow(tmp_path: Path):
    memory = make_memory(tmp_path)
    created = {
        "semantic": memory.remember("用户喜欢安静酒店", kind="semantic"),
        "procedural": memory.remember("以后每个阶段都写中文报告", kind="procedural"),
        "episodic": memory.remember("用户今天讨论了企业级记忆系统", kind="episodic"),
    }

    records = {kind: memory._sqlite.get_record(memory_id) for kind, memory_id in created.items()}
    before_forget = memory.search("酒店和流程偏好", top_k=10)
    forgotten = memory.forget(created["semantic"], reason="data-flow test")
    deleted_record = memory._sqlite.get_record(created["semantic"])
    after_forget = memory.search("酒店和流程偏好", top_k=10)

    emit_flow(
        "durable_memory.semantic_procedural_episodic_search_forget",
        [
            {"from": "Memory.remember(kind=semantic)", "to": "memory_records + vector_index", "record": records["semantic"]},
            {"from": "Memory.remember(kind=procedural)", "to": "memory_records + vector_index", "record": records["procedural"]},
            {"from": "Memory.remember(kind=episodic)", "to": "memory_records + vector_index", "record": records["episodic"]},
            {
                "from": "Memory.search(query)",
                "to": "embedding -> vector_index.search -> SQLite record hydration",
                "results": [result.model_dump(mode="json") for result in before_forget],
            },
            {
                "from": "Memory.forget(semantic_id)",
                "to": "SQLite status=deleted + vector_index.delete + audit",
                "forgotten": forgotten,
                "deleted_record": deleted_record,
            },
            {
                "from": "Memory.search(query) after forget",
                "to": "semantic memory filtered out",
                "results": [result.model_dump(mode="json") for result in after_forget],
            },
        ],
    )

    assert {record.kind for record in records.values() if record is not None} == {
        MemoryKind.SEMANTIC,
        MemoryKind.PROCEDURAL,
        MemoryKind.EPISODIC,
    }
    assert forgotten is True
    assert deleted_record is not None
    assert deleted_record.status == MemoryStatus.DELETED
    assert created["semantic"] not in [result.memory_id for result in after_forget]


def test_summary_export_import_data_flow(tmp_path: Path):
    source = make_memory(tmp_path / "source")
    target = make_memory(tmp_path / "target")

    source.update_summary("用户正在构建企业级本地记忆系统。")
    memory_id = source.remember("用户喜欢小步提交", kind="procedural")
    markdown = source.export("markdown")
    jsonl = source.export("jsonl")
    imported_ids = target.import_memories(jsonl, source="jsonl_flow")
    imported_results = target.search("小步提交", top_k=3)

    emit_flow(
        "summary.export_import",
        [
            {"from": "Memory.update_summary", "to": "SQLite memory_summaries", "summary": source.get_summary()},
            {"from": "Memory.remember(kind=procedural)", "to": "SQLite memory_records + vector_index", "memory_id": memory_id},
            {"from": "SQLite summaries + active records", "to": "Memory.export('markdown')", "markdown": markdown},
            {"from": "SQLite active records", "to": "Memory.export('jsonl')", "jsonl": jsonl},
            {"from": "jsonl rows", "to": "target.import_memories -> target.remember", "imported_ids": imported_ids},
            {
                "from": "target Memory.search",
                "to": "imported memory result",
                "results": [result.model_dump(mode="json") for result in imported_results],
            },
        ],
    )

    assert source.get_summary() == "用户正在构建企业级本地记忆系统。"
    assert "# Memory Export" in markdown
    assert "用户喜欢小步提交" in jsonl
    assert len(imported_ids) == 1
    assert imported_results[0].content == "用户喜欢小步提交"


def test_redaction_classifier_embedding_data_flow():
    raw = "Authorization: Bearer abc.def.ghi 用户喜欢安静酒店"
    redacted = redact_text(raw)
    classification = classify_memory_candidate(redacted.text)
    fake_provider = FakeEmbeddingProvider(dimension=8)
    vector_1 = fake_provider.embed(redacted.text)
    vector_2 = fake_provider.embed(redacted.text)
    bge_provider = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")

    emit_flow(
        "redaction.classifier.embedding",
        [
            {"from": "raw text", "to": "redact_text", "input": raw, "output": redacted},
            {"from": "redacted text", "to": "classify_memory_candidate", "classification": classification},
            {"from": "classification text", "to": "FakeEmbeddingProvider.embed", "vector": vector_1},
            {
                "from": "BGEM3EmbeddingProvider.__init__",
                "to": "lazy model state",
                "model_loaded": bge_provider._model is not None,
            },
        ],
    )

    assert "abc.def.ghi" not in redacted.text
    assert classification.kind == MemoryKind.SEMANTIC
    assert vector_1 == vector_2
    assert bge_provider._model is None


def test_qdrant_index_backend_data_flow():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(
        client=client,
        collection_name="agent_memories_v1",
        vector_size=1024,
    )
    record = make_record("mem_qdrant_flow")

    index.ensure_collection()
    index.upsert_memory(record, [0.1] * 1024)
    point_id, point = next(iter(client.points["agent_memories_v1"].items()))
    results = index.search([0.1] * 1024, {"tenant_id": "local"}, top_k=3)
    index.delete_memory(record.memory_id)

    emit_flow(
        "qdrant.index_backend",
        [
            {
                "from": "QdrantMemoryIndex.ensure_collection",
                "to": "FakeQdrantClient.collections",
                "collection": "agent_memories_v1",
                "vector_size": client.collections["agent_memories_v1"].size,
                "distance": client.collections["agent_memories_v1"].distance.value,
            },
            {
                "from": "MemoryRecord + vector",
                "to": "Qdrant point payload",
                "memory_id": record.memory_id,
                "qdrant_point_id": point_id,
                "payload": point.payload,
            },
            {"from": "Qdrant query_points", "to": "search result payload", "results": results},
            {"from": "QdrantMemoryIndex.delete_memory", "to": "client.delete", "deleted": bool(client.deleted)},
        ],
    )

    assert client.collections["agent_memories_v1"].size == 1024
    assert results[0]["memory_id"] == record.memory_id
    assert client.deleted


def test_sqlite_store_direct_interfaces_data_flow(tmp_path: Path):
    store = SQLiteMemoryStore(str(tmp_path / "memory.sqlite3"))
    source = SourceRef(
        source_id="src_flow",
        source_type="manual",
        source_ref="test",
        excerpt="用户喜欢安静酒店",
        metadata={"channel": "unit-test"},
    )
    record = make_record("mem_sqlite_flow")
    record.source_id = source.source_id

    store.set_kv("reset_flag", True)
    store.insert_source(source)
    store.insert_record(record)
    event_id = store.enqueue_outbox(
        "memory.semantic_candidate.created",
        {"text": "用户喜欢安静酒店"},
        dedupe_key="flow:1",
    )
    store.upsert_summary("local", "default", "lazyaiX-agent-corp-1", "project", "项目摘要")
    fetched = store.get_record(record.memory_id)
    listed = store.list_records([record.memory_id])
    active_before_delete = store.list_active_records()
    marked = store.mark_deleted(record.memory_id)
    active_after_delete = store.list_active_records()
    summary = store.get_summary("local", "default", "lazyaiX-agent-corp-1", "project")
    counts = store.counts()

    emit_flow(
        "sqlite.store_direct_interfaces",
        [
            {"from": "set_kv('reset_flag', True)", "to": "memory_kv", "retrieved": store.get_kv("reset_flag")},
            {"from": "SourceRef", "to": "memory_sources", "source_id": source.source_id},
            {"from": "MemoryRecord", "to": "memory_records", "record": fetched},
            {"from": "enqueue_outbox", "to": "memory_outbox", "event_id": event_id, "rows": store.list_outbox()},
            {"from": "upsert_summary", "to": "memory_summaries", "summary": summary},
            {"from": "list_records", "to": "MemoryRecord list", "records": listed},
            {"from": "list_active_records before delete", "to": "active records", "records": active_before_delete},
            {"from": "mark_deleted", "to": "memory_records.status=deleted", "marked": marked},
            {"from": "list_active_records after delete", "to": "deleted record hidden", "records": active_after_delete},
            {"from": "SQLite tables", "to": "counts", "counts": counts},
        ],
    )

    assert store.get_kv("reset_flag") is True
    assert event_id is not None
    assert fetched is not None
    assert fetched.source_id == source.source_id
    assert len(listed) == 1
    assert len(active_before_delete) == 1
    assert marked is True
    assert active_after_delete == []
    assert summary == "项目摘要"
    assert counts.kv == 1
    assert counts.records == 1
    assert counts.sources == 1
    assert counts.outbox == 1
    assert counts.summaries == 1


def test_agent_contract_to_memory_data_flow(tmp_path: Path):
    context = Context()
    memory = make_memory(tmp_path)
    agent = Agent(context=context, memory=memory)
    agent.model.complete = lambda prompt: "测试回复"
    agent.skill.decide = lambda user_input, llm_response, context, memory: {
        "action": "direct",
        "response": "测试回复",
    }

    response = agent.process_turn("你好")
    history = memory.retrieve("history")
    outbox = memory._sqlite.list_outbox()
    counts = memory.debug_counts()

    emit_flow(
        "agent.process_turn_to_memory",
        [
            {"from": "user input", "to": "Agent.process_turn", "input": "你好"},
            {"from": "Agent.context.update", "to": "Context state", "context": context.get()},
            {"from": "Model.complete + Skill.decide", "to": "response", "response": response},
            {"from": "Agent._remember", "to": "Memory.store('history')", "history": history},
            {"from": "Memory.store('history')", "to": "SQLite memory_kv", "key": "history"},
            {"from": "Memory.store('history')", "to": "SQLite memory_outbox", "outbox": outbox},
            {"from": "SQLite tables", "to": "Memory.debug_counts", "counts": counts},
        ],
    )

    assert response == "测试回复"
    assert history == [{"input": "你好", "response": "测试回复"}]
    assert len(outbox) == 1
    assert counts.kv == 1
    assert counts.outbox == 1
