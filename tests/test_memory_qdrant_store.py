from datetime import datetime
from uuid import UUID

from memory.backends.qdrant_store import QdrantMemoryIndex
from memory.models import MemoryKind, MemoryRecord, MemoryScope


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


def make_record():
    return MemoryRecord(
        memory_id="mem_1",
        tenant_id="local",
        user_id="default",
        project_id="lazyaiX-agent-corp-1",
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        content="用户喜欢安静酒店",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_ensure_collection_creates_1024_cosine_collection():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(
        client=client,
        collection_name="agent_memories_v1",
        vector_size=1024,
    )

    index.ensure_collection()

    config = client.collections["agent_memories_v1"]
    assert config.size == 1024
    assert config.distance.value == "Cosine"


def test_upsert_memory_writes_payload():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(
        client=client,
        collection_name="agent_memories_v1",
        vector_size=1024,
    )
    record = make_record()

    index.upsert_memory(record, [0.1] * 1024)

    point = next(iter(client.points["agent_memories_v1"].values()))
    assert point.payload["memory_id"] == "mem_1"
    assert point.payload["tenant_id"] == "local"
    assert point.payload["project_id"] == "lazyaiX-agent-corp-1"
    assert point.payload["status"] == "active"


def test_upsert_memory_uses_qdrant_valid_uuid_point_id():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(
        client=client,
        collection_name="agent_memories_v1",
        vector_size=1024,
    )

    index.upsert_memory(make_record(), [0.1] * 1024)

    point_id = next(iter(client.points["agent_memories_v1"].keys()))
    UUID(str(point_id))
    assert point_id != "mem_1"


def test_search_returns_payload_results():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(
        client=client,
        collection_name="agent_memories_v1",
        vector_size=1024,
    )
    index.upsert_memory(make_record(), [0.1] * 1024)

    results = index.search([0.1] * 1024, {"tenant_id": "local"}, top_k=3)

    assert results[0]["memory_id"] == "mem_1"
    assert results[0]["score"] == 0.9


def test_delete_memory_calls_qdrant_delete():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(
        client=client,
        collection_name="agent_memories_v1",
        vector_size=1024,
    )

    index.delete_memory("mem_1")

    assert client.deleted
