from pathlib import Path

from memory import Memory
from memory.embeddings import FakeEmbeddingProvider
from memory.extractors import RuleBasedMemoryExtractor
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


class StaticBatchExtractor:
    def __init__(self, classifications: list[MemoryClassification]):
        self.classifications = classifications
        self.seen_texts = []

    def extract_many(self, text: str) -> list[MemoryClassification]:
        self.seen_texts.append(text)
        return self.classifications


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


def test_process_outbox_skips_long_term_memory_meta_question(tmp_path: Path):
    memory = make_memory(tmp_path, candidate_extractor=RuleBasedMemoryExtractor())
    memory.store(
        "history",
        [
            {
                "input": "你基于长期记忆，分别说说我在合同、路演、会议方面有哪些偏好？",
                "response": "根据长期记忆，目前合同暂无相关记录。",
            }
        ],
    )

    result = memory.process_outbox(limit=10)

    row = memory._sqlite.list_outbox()[0]

    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert row["status"] == "skipped"
    assert memory._sqlite.list_active_records() == []


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
    assert extractor.seen_texts == ["我喜欢安静一点的酒店"]
    assert record.content == "用户偏好入住安静的酒店。"
    assert record.confidence == 0.91
    assert record.importance == 0.82
    assert row["payload"]["worker_result"]["content"] == "用户偏好入住安静的酒店。"


def test_process_outbox_extracts_from_user_input_without_assistant_response(tmp_path: Path):
    extractor = StaticExtractor(
        MemoryClassification(
            should_remember=True,
            kind=MemoryKind.PROCEDURAL,
            content="合同审核前应先检查续费条款和自动扣款。",
            confidence=0.91,
            importance=0.84,
            reason="流程偏好",
        )
    )
    memory = make_memory(tmp_path, candidate_extractor=extractor)
    memory.store(
        "history",
        [
            {
                "input": "以后如果让我看合同，先帮我确认续费和自动扣款。",
                "response": "已记住这条合同审核偏好。",
            }
        ],
    )

    result = memory.process_outbox(limit=10)

    assert result["processed"] == 1
    assert extractor.seen_texts == ["以后如果让我看合同，先帮我确认续费和自动扣款。"]


def test_process_outbox_remembers_multiple_items_with_time_metadata(tmp_path: Path):
    extractor = StaticBatchExtractor(
        [
            MemoryClassification(
                should_remember=True,
                kind=MemoryKind.SEMANTIC,
                content="用户偏好在周三上午处理预算复盘。",
                confidence=0.92,
                importance=0.73,
                reason="稳定的时间偏好",
            ),
            MemoryClassification(
                should_remember=True,
                kind=MemoryKind.EPISODIC,
                content="用户在 2026-07-07 提到上次预算复盘遗漏了供应商尾款。",
                confidence=0.89,
                importance=0.68,
                reason="一次性历史事件",
            ),
            MemoryClassification(
                should_remember=True,
                kind=MemoryKind.PROCEDURAL,
                content="预算复盘时应先检查供应商尾款。",
                confidence=0.9,
                importance=0.86,
                reason="后续流程要求",
            ),
            MemoryClassification(
                should_remember=True,
                kind=MemoryKind.SUMMARY,
                content="用户关注预算复盘中的供应商尾款，并偏好周三上午处理。",
                confidence=0.85,
                importance=0.8,
                reason="压缩摘要",
            ),
        ]
    )
    memory = make_memory(tmp_path, candidate_extractor=extractor)
    memory.store(
        "history",
        [
            {
                "input": "我周三上午比较适合看预算复盘。上次漏了供应商尾款，以后复盘先帮我查这个。",
                "response": "我会在后续预算复盘前优先检查供应商尾款。",
            }
        ],
    )

    result = memory.process_outbox(limit=10)

    row = memory._sqlite.list_outbox()[0]
    records = memory._sqlite.list_active_records()
    records_by_kind = {record.kind: record for record in records}
    worker_result = row["payload"]["worker_result"]

    assert result["processed"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert len(result["remembered_ids"]) == 3
    assert {record.kind for record in records} == {
        MemoryKind.SEMANTIC,
        MemoryKind.EPISODIC,
        MemoryKind.PROCEDURAL,
    }
    assert memory.get_summary() == "用户关注预算复盘中的供应商尾款，并偏好周三上午处理。"
    assert worker_result["processed_items"] == 4
    assert [item["kind"] for item in worker_result["items"]] == [
        "semantic",
        "episodic",
        "procedural",
        "summary",
    ]
    assert worker_result["items"][3]["summary_updated"] is True
    for record in records:
        assert record.metadata["outbox_event_id"] == row["event_id"]
        assert record.metadata["source_event_created_at"] == row["created_at"]
        assert record.metadata["extracted_at"]
        assert record.metadata["observed_at"] is None
    assert records_by_kind[MemoryKind.PROCEDURAL].content == "预算复盘时应先检查供应商尾款。"


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
