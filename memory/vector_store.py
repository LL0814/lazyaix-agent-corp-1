"""Vector memory backed by local Qdrant."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from .embedding import OllamaEmbedder


class QdrantConversationMemory:
    """Store and search complete conversation turns in Qdrant."""

    def __init__(
        self,
        embedder: OllamaEmbedder | None = None,
        base_url: str | None = None,
        collection: str | None = None,
        timeout: float | None = None,
        vector_size: int | None = None,
    ) -> None:
        self.embedder = embedder or OllamaEmbedder()
        self.base_url = (base_url or os.environ.get("QDRANT_URL") or "http://localhost:6333").rstrip("/")
        self.collection = collection or os.environ.get("QDRANT_COLLECTION") or "agent_conversations"
        self.timeout = float(timeout or os.environ.get("QDRANT_TIMEOUT", "3"))
        self.vector_size = int(vector_size or os.environ.get("QDRANT_VECTOR_SIZE", "1024"))
        self.distance = os.environ.get("QDRANT_DISTANCE", "Cosine")

    def search(self, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Search with the raw user prompt only."""
        vector = self.embedder.embed(query)
        if not vector:
            return []

        top_k = int(limit or os.environ.get("VECTOR_MEMORY_TOP_K", "5"))
        score_threshold = float(
            os.environ.get("VECTOR_MEMORY_SCORE_THRESHOLD", "0.65")
        )
        payload: dict[str, Any] = {
            "vector": vector,
            "limit": top_k,
            "with_payload": True,
            "score_threshold": score_threshold,
        }

        data = self._request_json(
            "POST",
            f"/collections/{self.collection}/points/search",
            payload,
        )
        result = data.get("result")
        if not isinstance(result, list):
            return []

        memories = []
        for item in result:
            if not isinstance(item, dict):
                continue
            score = item.get("score")
            if isinstance(score, (float, int)) and float(score) < score_threshold:
                continue
            point_payload = item.get("payload") or {}
            if not isinstance(point_payload, dict):
                point_payload = {}
            memories.append(
                {
                    "score": score,
                    "text": point_payload.get("text", ""),
                    "user_input": point_payload.get("user_input", ""),
                    "response": point_payload.get("response", ""),
                    "created_at": point_payload.get("created_at", ""),
                }
            )
        return memories

    def add_turn(self, user_input: str, response: str) -> bool:
        """Embed and store one complete user/assistant turn."""
        text = self._format_turn(user_input, response)
        vector = self.embedder.embed(text)
        if not vector:
            return False

        if not self._ensure_collection(len(vector)):
            return False

        point = {
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": {
                "type": "conversation_turn",
                "text": text,
                "user_input": user_input,
                "response": response,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        data = self._request_json(
            "PUT",
            f"/collections/{self.collection}/points?wait=true",
            {"points": [point]},
        )
        return data.get("status") in {"ok", "accepted"} or "result" in data

    def _format_turn(self, user_input: str, response: str) -> str:
        return f"用户：{user_input.strip()}\n助手：{response.strip()}"

    def _ensure_collection(self, vector_size: int) -> bool:
        existing = self._request_json("GET", f"/collections/{self.collection}")
        if existing.get("result"):
            return True

        size = vector_size or self.vector_size
        created = self._request_json(
            "PUT",
            f"/collections/{self.collection}",
            {
                "vectors": {
                    "size": size,
                    "distance": self.distance,
                }
            },
        )
        return created.get("status") in {"ok", "accepted"} or "result" in created

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                return {}
            return {}
        except (OSError, URLError, json.JSONDecodeError):
            return {}
