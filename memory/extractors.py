"""Memory candidate extractors."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from openai import OpenAI

from memory.classifier import classify_memory_candidate
from memory.config import MemoryConfig
from memory.models import MemoryClassification, MemoryKind


class MemoryCandidateExtractor(Protocol):
    def extract(self, text: str) -> MemoryClassification:
        """Classify and optionally normalize a candidate memory text."""


class RuleBasedMemoryExtractor:
    def extract(self, text: str) -> MemoryClassification:
        return classify_memory_candidate(text)


class DeepSeekMemoryExtractor:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-pro",
        base_url: str = "https://api.deepseek.com",
        client: Any | None = None,
        fallback: MemoryCandidateExtractor | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.fallback = fallback
        self.client = client or (OpenAI(api_key=api_key, base_url=base_url) if api_key else None)

    def extract(self, text: str) -> MemoryClassification:
        if self.client is None:
            return self._fallback(text, "DeepSeek API Key 未配置")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": text},
                ],
                temperature=0,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("DeepSeek 返回空内容")
            return self._parse_response(content, original_text=text)
        except Exception as exc:
            return self._fallback(text, f"DeepSeek 抽取失败：{exc}")

    @staticmethod
    def _system_prompt() -> str:
        kinds = ", ".join(kind.value for kind in MemoryKind)
        return (
            "你是企业级 Agent 的长期记忆抽取器。"
            "请判断这段对话是否值得写入长期记忆，并把值得记的内容改写成一句稳定、简洁、无第一人称的事实。"
            "只输出合法 JSON，不要输出 markdown。"
            f"kind 只能是这些值之一：{kinds}。"
            "JSON 字段：should_remember(boolean), kind(string), content(string|null), "
            "confidence(number 0-1), importance(number 0-1), reason(string)。"
            "不要记录一次性寒暄、临时状态、无意义确认。"
            "procedural 用于用户要求的工作方式或流程偏好；semantic 用于稳定偏好、事实和项目背景；"
            "episodic 用于一次性事件；summary 用于压缩摘要。"
        )

    def _parse_response(self, raw: str, *, original_text: str) -> MemoryClassification:
        data = json.loads(self._strip_markdown_fence(raw))
        should_remember = bool(data.get("should_remember", False))
        kind = MemoryKind(str(data.get("kind", MemoryKind.EPISODIC.value)))
        content = data.get("content")
        normalized_content = str(content).strip() if content is not None else None
        if should_remember and not normalized_content:
            normalized_content = original_text.strip()
        return MemoryClassification(
            should_remember=should_remember,
            kind=kind,
            content=normalized_content or None,
            confidence=self._clamp_float(data.get("confidence", 0.5)),
            importance=self._clamp_float(data.get("importance", 0.5)),
            reason=str(data.get("reason", "")).strip(),
        )

    @staticmethod
    def _strip_markdown_fence(raw: str) -> str:
        stripped = raw.strip()
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
        return match.group(1).strip() if match else stripped

    @staticmethod
    def _clamp_float(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = 0.5
        return max(0.0, min(1.0, parsed))

    def _fallback(self, text: str, reason: str) -> MemoryClassification:
        if self.fallback is None:
            return MemoryClassification(
                should_remember=False,
                kind=MemoryKind.EPISODIC,
                confidence=0.0,
                importance=0.0,
                reason=reason,
            )
        return self.fallback.extract(text)


def create_memory_candidate_extractor(config: MemoryConfig) -> MemoryCandidateExtractor:
    rule = RuleBasedMemoryExtractor()
    if config.extractor_provider != "deepseek":
        return rule
    return DeepSeekMemoryExtractor(
        api_key=config.deepseek_api_key,
        model=config.deepseek_model,
        base_url=config.deepseek_base_url,
        fallback=rule if config.extractor_fallback_to_rule else None,
    )
