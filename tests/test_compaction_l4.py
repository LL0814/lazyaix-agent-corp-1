"""Tests for L4 compact_history and adapter."""

from context.adapter import RuleBasedCompactAdapter
from context.compaction import compact_history
from context.config import CONTEXT_LIMIT


def test_compact_history_replaces_messages():
    messages = [{"role": "user", "content": "what is the weather?"}]
    result = compact_history(messages)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert result[0]["content"].startswith("[Compacted]")
    assert "_transcript_path" in result[0]


def test_compact_history_adapter_failure_uses_fallback():
    class BrokenAdapter:
        def summarize_history(self, messages):
            raise RuntimeError("boom")

    messages = [{"role": "user", "content": "hello"}]
    result = compact_history(messages, adapter=BrokenAdapter())
    assert "(empty summary)" in result[0]["content"]


def test_rule_based_adapter_summary():
    adapter = RuleBasedCompactAdapter()
    messages = [
        {"role": "user", "content": "what is the weather in 'Beijing'?"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu1", "name": "weather", "input": {"city": "Beijing"}}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "sunny"}],
        },
    ]
    summary = adapter.summarize_history(messages)
    assert "weather" in summary
    assert "Beijing" in summary
