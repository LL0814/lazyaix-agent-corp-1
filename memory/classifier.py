"""Rule-based memory candidate classifier."""

from __future__ import annotations

from memory.models import MemoryClassification, MemoryKind


PROCEDURAL_KEYWORDS = (
    "以后",
    "每次",
    "总是",
    "不要",
    "必须",
    "流程",
    "阶段报告",
    "等待确认",
)
PREFERENCE_KEYWORDS = (
    "喜欢",
    "偏好",
    "习惯",
    "希望",
    "倾向",
    "使用",
    "正在构建",
    "项目",
)


def classify_memory_candidate(text: str) -> MemoryClassification:
    stripped = text.strip()
    if len(stripped) < 6:
        return MemoryClassification(
            should_remember=False,
            kind=MemoryKind.EPISODIC,
            confidence=0.9,
            importance=0.1,
            reason="内容过短，通常不是稳定记忆",
        )

    if any(keyword in stripped for keyword in PROCEDURAL_KEYWORDS):
        return MemoryClassification(
            should_remember=True,
            kind=MemoryKind.PROCEDURAL,
            confidence=0.8,
            importance=0.8,
            reason="命中流程或工作方式偏好",
        )

    if any(keyword in stripped for keyword in PREFERENCE_KEYWORDS):
        return MemoryClassification(
            should_remember=True,
            kind=MemoryKind.SEMANTIC,
            confidence=0.75,
            importance=0.7,
            reason="命中稳定偏好或项目事实",
        )

    return MemoryClassification(
        should_remember=False,
        kind=MemoryKind.EPISODIC,
        confidence=0.6,
        importance=0.3,
        reason="未命中稳定记忆规则",
    )
