"""Tests for L4 compact_history and adapter."""

import pytest

from context.adapter import RuleBasedCompactAdapter
from context.compaction import CompactCircuitBreaker, compact_history
from context.config import CONTEXT_LIMIT


def test_compact_history_replaces_messages():
    messages = [{"role": "user", "content": "what is the weather?"}]
    result = compact_history(messages)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert result[0]["content"].startswith("[Compacted]")
    assert "_transcript_path" in result[0]


def test_compact_history_adapter_failure_raises():
    class BrokenAdapter:
        def summarize_history(self, messages):
            raise RuntimeError("boom")

    messages = [{"role": "user", "content": "hello"}]
    with pytest.raises(RuntimeError, match="boom"):
        compact_history(messages, adapter=BrokenAdapter())


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


def test_circuit_breaker_opens_after_three_failures():
    breaker = CompactCircuitBreaker(max_failures=3)

    def fail():
        raise RuntimeError("boom")

    for _ in range(3):
        try:
            breaker.call(fail)
        except RuntimeError:
            pass

    with pytest.raises(RuntimeError, match="circuit breaker open"):
        breaker.call(fail)


def test_circuit_breaker_resets_on_success():
    breaker = CompactCircuitBreaker(max_failures=3)

    def fail():
        raise RuntimeError("boom")

    def succeed():
        return "ok"

    with pytest.raises(RuntimeError):
        breaker.call(fail)
    with pytest.raises(RuntimeError):
        breaker.call(fail)
    breaker.call(succeed)  # reset
    with pytest.raises(RuntimeError):
        breaker.call(fail)     # should not open yet
    assert breaker.failures == 1
