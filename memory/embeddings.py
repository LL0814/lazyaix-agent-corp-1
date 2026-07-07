"""Embedding providers for semantic memory."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for text."""


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 1024):
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed = int(digest[:16], 16)
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]


class OllamaEmbeddingProvider:
    def __init__(
        self,
        model_name: str = "bge-m3",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 120.0,
    ):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def embed(self, text: str) -> list[float]:
        payload = json.dumps(
            {"model": self.model_name, "input": text},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama embedding HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(
                f"Ollama embedding service is unavailable at {self.base_url}: {exc.reason}"
            ) from exc

        embeddings = data.get("embeddings")
        if not embeddings or not isinstance(embeddings, list) or not embeddings[0]:
            raise RuntimeError(f"Ollama embedding response missing embeddings: {data}")
        return [float(value) for value in embeddings[0]]


class BGEM3EmbeddingProvider:
    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        use_fp16: bool = True,
        max_length: int = 8192,
    ):
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.max_length = max_length
        self._model = None

    def _import_model_class(self):
        from FlagEmbedding import BGEM3FlagModel

        return BGEM3FlagModel

    def _load_model(self):
        if self._model is None:
            try:
                model_class = self._import_model_class()
            except ImportError as exc:
                raise RuntimeError(
                    "FlagEmbedding is required for BGEM3EmbeddingProvider. "
                    "Install project dependencies before using BGE-M3 embeddings."
                ) from exc
            self._model = model_class(self.model_name, use_fp16=self.use_fp16)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load_model()
        output = model.encode([text], batch_size=1, max_length=self.max_length)
        dense = output["dense_vecs"][0]
        return [float(value) for value in dense]


def create_embedding_provider(config: Any) -> EmbeddingProvider:
    provider = str(getattr(config, "embedding_provider", "ollama")).lower()
    if provider == "ollama":
        return OllamaEmbeddingProvider(
            model_name=getattr(config, "embedding_model", "bge-m3"),
            base_url=getattr(config, "ollama_base_url", "http://localhost:11434"),
            timeout_seconds=float(getattr(config, "ollama_timeout_seconds", 120.0)),
        )
    if provider in {"flagembedding", "bge-m3", "local"}:
        model_name = getattr(config, "embedding_model", "BAAI/bge-m3")
        if model_name == "bge-m3":
            model_name = "BAAI/bge-m3"
        return BGEM3EmbeddingProvider(model_name=model_name)
    raise ValueError(f"Unsupported memory embedding provider: {provider}")
