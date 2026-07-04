"""Embedding client backed by local Ollama."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import request
from urllib.error import URLError


class OllamaEmbedder:
    """Create embeddings with Ollama's local HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or os.environ.get("OLLAMA_EMBED_MODEL") or "bge-m3"
        self.timeout = float(timeout or os.environ.get("OLLAMA_TIMEOUT", "5"))

    def embed(self, text: str) -> list[float]:
        """Return one embedding vector for text, or an empty list on failure."""
        normalized_text = text.strip()
        if not normalized_text:
            return []

        vector = self._embed_with_new_api(normalized_text)
        if vector:
            return vector
        return self._embed_with_legacy_api(normalized_text)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError):
            return {}

    def _embed_with_new_api(self, text: str) -> list[float]:
        data = self._post_json("/api/embed", {"model": self.model, "input": text})
        embeddings = data.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            vector = embeddings[0]
            if isinstance(vector, list):
                return [float(value) for value in vector]
        return []

    def _embed_with_legacy_api(self, text: str) -> list[float]:
        data = self._post_json("/api/embeddings", {"model": self.model, "prompt": text})
        embedding = data.get("embedding")
        if isinstance(embedding, list):
            return [float(value) for value in embedding]
        return []
