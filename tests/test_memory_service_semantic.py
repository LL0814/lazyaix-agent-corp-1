from pathlib import Path

from memory import Memory
from memory.embeddings import FakeEmbeddingProvider


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
            if record.status.value != "active":
                continue
            results.append({"memory_id": memory_id, "score": 0.9})
        return results[:top_k]

    def delete_memory(self, memory_id):
        self.deleted.add(memory_id)


class IndexThatMissesContract(FakeIndex):
    def search(self, vector, filters, top_k):
        return [
            result
            for result in super().search(vector, filters, top_k=100)
            if "合同" not in self.points[result["memory_id"]]["record"].content
        ][:top_k]


def make_memory(tmp_path: Path):
    return Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
    )


def test_remember_creates_searchable_memory(tmp_path: Path):
    memory = make_memory(tmp_path)

    memory_id = memory.remember("用户喜欢安静、交通方便的酒店", kind="semantic")
    results = memory.search("住宿偏好", top_k=3)

    assert memory_id
    assert results[0].memory_id == memory_id
    assert results[0].content == "用户喜欢安静、交通方便的酒店"


def test_search_filters_project_by_default(tmp_path: Path):
    memory = make_memory(tmp_path)
    other = Memory(
        config={
            "MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3"),
            "MEMORY_PROJECT_ID": "other-project",
        },
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=memory._vector_index,
    )

    memory.remember("当前项目偏好 Qdrant", kind="semantic")
    other.remember("其他项目偏好 Milvus", kind="semantic")

    results = memory.search("项目向量库", top_k=10)

    assert [result.content for result in results] == ["当前项目偏好 Qdrant"]


def test_search_adds_sqlite_keyword_fallback_when_vector_misses_relevant_memory(
    tmp_path: Path,
):
    memory = Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=IndexThatMissesContract(),
    )
    memory.remember("合同审核前应先检查续费条款和自动扣款。", kind="procedural")
    memory.remember("路演时用户偏好先讲风险边界，再讲收益空间。", kind="semantic")

    results = memory.search("合同和路演分别有什么偏好？", top_k=2)

    assert "合同审核前应先检查续费条款和自动扣款。" in [
        result.content for result in results
    ]
    assert "路演时用户偏好先讲风险边界，再讲收益空间。" in [
        result.content for result in results
    ]


def test_search_filters_memory_recall_meta_answers_from_results(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory.remember(
        "Q: 你基于长期记忆，分别说说我在合同方面有哪些偏好？\n"
        "A: 根据你目前的长期记忆，合同暂无相关长期记忆。",
        kind="semantic",
    )
    memory.remember("合同审核前应先检查续费条款和自动扣款。", kind="procedural")

    results = memory.search("合同方面有哪些偏好？", top_k=10)

    assert [result.content for result in results] == [
        "合同审核前应先检查续费条款和自动扣款。"
    ]


def test_forget_hides_memory_from_search(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory_id = memory.remember("用户喜欢安静酒店", kind="semantic")

    assert memory.forget(memory_id, reason="人工删除") is True

    assert memory.search("酒店", top_k=3) == []
