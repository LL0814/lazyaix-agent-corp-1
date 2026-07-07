"""Qdrant vector index backend for semantic memories."""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from memory.models import MemoryRecord


class QdrantMemoryIndex:
    def __init__(
        self,
        client: QdrantClient | None = None,
        url: str = "http://localhost:6333",
        collection_name: str = "agent_memories_v1",
        vector_size: int = 1024,
    ):
        self.client = client or QdrantClient(url=url)
        self.collection_name = collection_name
        self.vector_size = vector_size

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.vector_size,
                distance=Distance.COSINE,
            ),
        )

    @staticmethod
    def _point_id(memory_id: str) -> str:
        try:
            uuid.UUID(str(memory_id))
            return str(memory_id)
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(memory_id)))

    @staticmethod
    def _payload(record: MemoryRecord) -> dict[str, Any]:
        return {
            "memory_id": record.memory_id,
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "project_id": record.project_id,
            "thread_id": record.thread_id,
            "scope": record.scope.value,
            "kind": record.kind.value,
            "status": record.status.value,
            "confidence": record.confidence,
            "importance": record.importance,
            "sensitivity": record.sensitivity,
            "source_id": record.source_id,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        }

    def upsert_memory(self, record: MemoryRecord, vector: list[float]) -> None:
        self.ensure_collection()
        point = PointStruct(
            id=self._point_id(record.memory_id),
            vector=vector,
            payload=self._payload(record),
        )
        self.client.upsert(collection_name=self.collection_name, points=[point])

    @staticmethod
    def _filter(filters: dict[str, Any]) -> Filter | None:
        conditions = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in filters.items()
            if value is not None
        ]
        if not conditions:
            return None
        return Filter(must=conditions)

    def search(
        self,
        vector: list[float],
        filters: dict[str, Any],
        top_k: int,
    ) -> list[dict[str, Any]]:
        self.ensure_collection()
        result = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=self._filter(filters),
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "id": point.id,
                "score": float(point.score),
                **(point.payload or {}),
            }
            for point in result.points
        ]

    def delete_memory(self, memory_id: str) -> None:
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[self._point_id(memory_id)]),
        )
