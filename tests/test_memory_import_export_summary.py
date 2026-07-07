from pathlib import Path

from memory import Memory
from memory.embeddings import FakeEmbeddingProvider


class FakeIndex:
    def __init__(self):
        self.points = {}
        self.deleted = set()

    def upsert_memory(self, record, vector):
        self.points[record.memory_id] = record

    def search(self, vector, filters, top_k):
        results = []
        for memory_id, record in self.points.items():
            if memory_id in self.deleted:
                continue
            if record.tenant_id != filters.get("tenant_id"):
                continue
            if record.user_id != filters.get("user_id"):
                continue
            if record.project_id != filters.get("project_id"):
                continue
            results.append({"memory_id": memory_id, "score": 0.9})
        return results[:top_k]

    def delete_memory(self, memory_id):
        self.deleted.add(memory_id)


def make_memory(tmp_path: Path):
    return Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
    )


def test_summary_round_trip(tmp_path: Path):
    memory = make_memory(tmp_path)

    memory.update_summary("用户正在构建企业级本地记忆系统。")

    assert memory.get_summary() == "用户正在构建企业级本地记忆系统。"


def test_markdown_export_contains_summary_and_memory(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory.update_summary("用户偏好中文阶段报告。")
    memory.remember("用户使用 Qdrant 和 BGE-M3 构建记忆系统", kind="semantic")

    exported = memory.export("markdown")

    assert "# Memory Export" in exported
    assert "## Summary" in exported
    assert "用户偏好中文阶段报告。" in exported
    assert "用户使用 Qdrant 和 BGE-M3 构建记忆系统" in exported


def test_jsonl_export_import_round_trip(tmp_path: Path):
    source = make_memory(tmp_path / "source")
    target = make_memory(tmp_path / "target")
    source.remember("用户喜欢小步提交", kind="procedural")

    exported = source.export("jsonl")
    ids = target.import_memories(exported, source="jsonl_test")

    assert len(ids) == 1
    assert target.search("小步提交", top_k=3)[0].content == "用户喜欢小步提交"
