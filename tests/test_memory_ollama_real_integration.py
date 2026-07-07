from uuid import uuid4

from qdrant_client import QdrantClient

from memory import Memory
from memory.embeddings import OllamaEmbeddingProvider
from memory.models import MemoryKind, MemoryStatus


def make_real_memory(tmp_path, collection_name: str) -> Memory:
    return Memory(
        config={
            "MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3"),
            "MEMORY_EMBEDDING_PROVIDER": "ollama",
            "OLLAMA_EMBEDDING_MODEL": "bge-m3",
            "QDRANT_COLLECTION": collection_name,
            "MEMORY_EXTRACTOR_PROVIDER": "rule",
        }
    )


def test_memory_uses_ollama_provider_from_config(tmp_path):
    memory = make_real_memory(tmp_path, f"agent_memories_ollama_cfg_{uuid4().hex}")

    assert isinstance(memory._embedding_provider, OllamaEmbeddingProvider)
    assert memory._embedding_provider.model_name == "bge-m3"


def test_real_ollama_qdrant_sqlite_chain_covers_memory_kinds(tmp_path):
    collection = f"agent_memories_ollama_real_{uuid4().hex}"
    client = QdrantClient(url="http://localhost:6333")
    if client.collection_exists(collection):
        client.delete_collection(collection)
    memory = make_real_memory(tmp_path, collection)

    memory.store("current_requirement", {"destination": "成都", "days": 3})
    semantic_id = memory.remember("用户喜欢安静且靠近地铁的酒店", kind="semantic")
    procedural_id = memory.remember("以后每个工程步骤都要中文说明验证方式", kind="procedural")
    episodic_id = memory.remember("用户在 2026-07-07 测试了 loop.py 记忆链路", kind="episodic")
    memory.update_summary("用户正在验证 Ollama bge-m3 记忆系统。")

    results = memory.search("住宿偏好和工程汇报方式", top_k=5)
    remembered_kinds = {result.kind for result in results}
    changed = memory.forget(semantic_id, reason="真实链路 tombstone 测试")
    deleted_record = memory._sqlite.get_record(semantic_id)

    assert memory.retrieve("current_requirement") == {"destination": "成都", "days": 3}
    assert {MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL}.issubset(remembered_kinds)
    assert memory._sqlite.get_record(procedural_id).kind == MemoryKind.PROCEDURAL
    assert memory._sqlite.get_record(episodic_id).kind == MemoryKind.EPISODIC
    assert memory.get_summary() == "用户正在验证 Ollama bge-m3 记忆系统。"
    assert changed is True
    assert deleted_record.status == MemoryStatus.DELETED
    assert client.count(collection_name=collection, exact=True).count == 2

    client.delete_collection(collection)
