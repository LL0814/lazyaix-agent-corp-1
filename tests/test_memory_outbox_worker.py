from pathlib import Path

from memory import Memory
from memory.embeddings import FakeEmbeddingProvider
from memory.models import MemoryClassification, MemoryKind


class FakeIndex:
    def __init__(self):
        self.points = {}
        self.deleted = set()

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
            results.append({"memory_id": memory_id, "score": 0.9})
        return results[:top_k]

    def delete_memory(self, memory_id):
        self.deleted.add(memory_id)


class FailingIndex(FakeIndex):
    def upsert_memory(self, record, vector):
        raise RuntimeError("qdrant boom")


class StaticExtractor:
    def __init__(self, classification: MemoryClassification):
        self.classification = classification
        self.seen_texts = []

    def extract(self, text: str) -> MemoryClassification:
        self.seen_texts.append(text)
        return self.classification


def make_memory(tmp_path: Path, *, vector_index=None, candidate_extractor=None) -> Memory:
    return Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=vector_index or FakeIndex(),
        candidate_extractor=candidate_extractor,
    )


def test_process_outbox_remembers_semantic_and_procedural_candidates(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory.store(
        "history",
        [
            {"input": "用户喜欢安静酒店", "response": "已记录"},
            {"input": "以后每一步都写中文阶段报告", "response": "收到"},
        ],
    )

    result = memory.process_outbox(limit=10)

    rows = memory._sqlite.list_outbox()
    records = memory._sqlite.list_active_records()
    kinds = {record.kind for record in records}

    assert result["processed"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert len(result["remembered_ids"]) == 2
    assert {row["status"] for row in rows} == {"processed"}
    assert all(row["payload"]["worker_result"]["memory_id"] for row in rows)
    assert kinds == {MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL}
    assert len(memory._vector_index.points) == 2


def test_process_outbox_skips_low_value_candidate(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory.store("history", [{"input": "好的", "response": ""}])

    result = memory.process_outbox(limit=10)

    row = memory._sqlite.list_outbox()[0]
    records = memory._sqlite.list_active_records()

    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert row["status"] == "skipped"
    assert row["payload"]["worker_result"]["should_remember"] is False
    assert records == []


def test_process_outbox_marks_failed_when_remember_fails(tmp_path: Path):
    memory = make_memory(tmp_path, vector_index=FailingIndex())
    memory.store("history", [{"input": "用户喜欢安静酒店", "response": "已记录"}])

    result = memory.process_outbox(limit=10)

    row = memory._sqlite.list_outbox()[0]
    records = memory._sqlite.list_active_records()

    assert result["processed"] == 0
    assert result["skipped"] == 0
    assert result["failed"] == 1
    assert row["status"] == "failed"
    assert "qdrant boom" in row["last_error"]
    assert row["payload"]["worker_result"]["error"] == "qdrant boom"
    assert records == []


def test_process_outbox_respects_limit(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory.store(
        "history",
        [
            {"input": "用户喜欢安静酒店", "response": "已记录"},
            {"input": "用户偏好中文报告", "response": "已记录"},
        ],
    )

    result = memory.process_outbox(limit=1)

    rows = memory._sqlite.list_outbox()
    statuses = [row["status"] for row in rows]

    assert result["processed"] == 1
    assert statuses.count("processed") == 1
    assert statuses.count("pending") == 1


def test_process_outbox_stores_extractor_content_instead_of_raw_turn(tmp_path: Path):
    extractor = StaticExtractor(
        MemoryClassification(
            should_remember=True,
            kind=MemoryKind.SEMANTIC,
            content="用户偏好入住安静的酒店。",
            confidence=0.91,
            importance=0.82,
            reason="DeepSeek 抽取出的稳定偏好",
        )
    )
    memory = make_memory(tmp_path, candidate_extractor=extractor)
    memory.store("history", [{"input": "我喜欢安静一点的酒店", "response": "已记录"}])

    result = memory.process_outbox(limit=10)

    row = memory._sqlite.list_outbox()[0]
    record = memory._sqlite.list_active_records()[0]

    assert result["processed"] == 1
    assert extractor.seen_texts == ["Q: 我喜欢安静一点的酒店\nA: 已记录"]
    assert record.content == "用户偏好入住安静的酒店。"
    assert record.confidence == 0.91
    assert record.importance == 0.82
    assert row["payload"]["worker_result"]["content"] == "用户偏好入住安静的酒店。"


def test_process_outbox_updates_summary_table_for_summary_candidate(tmp_path: Path):
    extractor = StaticExtractor(
        MemoryClassification(
            should_remember=True,
            kind=MemoryKind.SUMMARY,
            content="用户正在验证 Ollama bge-m3 的长期记忆系统。",
            confidence=0.88,
            importance=0.9,
            reason="DeepSeek 抽取出的对话摘要",
        )
    )
    memory = make_memory(tmp_path, candidate_extractor=extractor)
    memory.store("history", [{"input": "总结一下当前记忆系统测试", "response": "好的"}])

    result = memory.process_outbox(limit=10)

    row = memory._sqlite.list_outbox()[0]

    assert result["processed"] == 1
    assert result["remembered_ids"] == []
    assert memory.get_summary() == "用户正在验证 Ollama bge-m3 的长期记忆系统。"
    assert memory._sqlite.list_active_records() == []
    assert memory._vector_index.points == {}
    assert row["payload"]["worker_result"]["kind"] == "summary"
