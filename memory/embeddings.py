"""Embedding providers for semantic memory."""

from __future__ import annotations

import hashlib
import random
from typing import Protocol


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
