"""Retrieval helpers for semantic memory search."""

from __future__ import annotations

from memory.models import MemoryRecord


def combined_score(vector_score: float, record: MemoryRecord) -> float:
    importance_bonus = record.importance * 0.1
    confidence_bonus = record.confidence * 0.1
    return vector_score + importance_bonus + confidence_bonus
