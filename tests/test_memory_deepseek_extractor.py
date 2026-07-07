from types import SimpleNamespace

from memory.extractors import DeepSeekMemoryExtractor, RuleBasedMemoryExtractor
from memory.models import MemoryKind


class FakeDeepSeekCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                )
            ]
        )


class FakeDeepSeekClient:
    def __init__(self, content: str):
        self.completions = FakeDeepSeekCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def test_deepseek_extractor_parses_json_and_uses_configured_model():
    client = FakeDeepSeekClient(
        """
        {
          "should_remember": true,
          "kind": "semantic",
          "content": "用户偏好入住安静的酒店。",
          "confidence": 0.91,
          "importance": 0.82,
          "reason": "明确表达了稳定住宿偏好"
        }
        """
    )
    extractor = DeepSeekMemoryExtractor(
        api_key="ds-key",
        model="deepseek-v4-pro",
        client=client,
    )

    result = extractor.extract("Q: 我喜欢安静一点的酒店\nA: 已记录")

    assert result.should_remember is True
    assert result.kind == MemoryKind.SEMANTIC
    assert result.content == "用户偏好入住安静的酒店。"
    assert result.confidence == 0.91
    assert result.importance == 0.82
    assert client.completions.calls[0]["model"] == "deepseek-v4-pro"


def test_deepseek_extractor_strips_markdown_fence():
    client = FakeDeepSeekClient(
        """```json
        {"should_remember": false, "kind": "episodic", "reason": "寒暄", "confidence": 0.8, "importance": 0.1}
        ```"""
    )
    extractor = DeepSeekMemoryExtractor(api_key="ds-key", client=client)

    result = extractor.extract("Q: 好的\nA:")

    assert result.should_remember is False
    assert result.kind == MemoryKind.EPISODIC
    assert result.reason == "寒暄"


def test_deepseek_extractor_falls_back_to_rule_when_json_is_invalid():
    client = FakeDeepSeekClient("not json")
    extractor = DeepSeekMemoryExtractor(
        api_key="ds-key",
        client=client,
        fallback=RuleBasedMemoryExtractor(),
    )

    result = extractor.extract("以后每一步都写中文阶段报告")

    assert result.should_remember is True
    assert result.kind == MemoryKind.PROCEDURAL
    assert "流程" in result.reason
