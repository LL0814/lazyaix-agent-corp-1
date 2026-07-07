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


def test_deepseek_extractor_parses_multiple_items_from_batch_json():
    client = FakeDeepSeekClient(
        """
        {
          "items": [
            {
              "should_remember": true,
              "kind": "semantic",
              "content": "用户偏好在周三上午处理预算复盘。",
              "confidence": 0.92,
              "importance": 0.73,
              "reason": "稳定的时间偏好"
            },
            {
              "should_remember": true,
              "kind": "episodic",
              "content": "用户在 2026-07-07 提到上次预算复盘遗漏了供应商尾款。",
              "observed_at": "2026-07-07",
              "confidence": 0.89,
              "importance": 0.68,
              "reason": "明确的一次性历史事件"
            },
            {
              "should_remember": true,
              "kind": "procedural",
              "content": "预算复盘时应先检查供应商尾款。",
              "confidence": 0.9,
              "importance": 0.86,
              "reason": "用户表达了后续流程要求"
            },
            {
              "should_remember": true,
              "kind": "summary",
              "content": "用户关注预算复盘中的供应商尾款，并偏好周三上午处理。",
              "confidence": 0.85,
              "importance": 0.8,
              "reason": "对当前长期偏好的压缩摘要"
            }
          ]
        }
        """
    )
    extractor = DeepSeekMemoryExtractor(
        api_key="ds-key",
        model="deepseek-v4-pro",
        client=client,
    )

    results = extractor.extract_many(
        "我周三上午比较适合看预算复盘。上次漏了供应商尾款，以后复盘先帮我查这个。"
    )

    assert [result.kind for result in results] == [
        MemoryKind.SEMANTIC,
        MemoryKind.EPISODIC,
        MemoryKind.PROCEDURAL,
        MemoryKind.SUMMARY,
    ]
    assert [result.content for result in results] == [
        "用户偏好在周三上午处理预算复盘。",
        "用户在 2026-07-07 提到上次预算复盘遗漏了供应商尾款。",
        "预算复盘时应先检查供应商尾款。",
        "用户关注预算复盘中的供应商尾款，并偏好周三上午处理。",
    ]
    assert results[1].observed_at == "2026-07-07"


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
