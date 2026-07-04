"""Unit tests for the Context module."""

import pytest

from context import Context
from context.compaction import reactive_compact


def test_update_appends_user_turn():
    ctx = Context()
    state = ctx.update("hello")

    assert len(state.recent_turns) == 1
    turn = state.recent_turns[0]
    assert turn.role == "user"
    assert turn.content_preview == "hello"
    assert turn.turn_id == 1


def test_update_truncates_old_turns():
    ctx = Context(config={"MAX_RECENT_TURNS": 2})
    ctx.update("first")
    ctx.update("second")
    state = ctx.update("third")

    assert len(state.recent_turns) == 2
    assert state.recent_turns[0].turn_id == 2
    assert state.recent_turns[1].turn_id == 3


def test_topic_inference_weather():
    ctx = Context()
    state = ctx.update("北京天气怎么样")

    assert state.topic.primary_topic == "weather"
    assert state.topic.intent == "query"


def test_topic_inference_math():
    ctx = Context()
    state = ctx.update("calculate 1 + 1")

    assert state.topic.primary_topic == "math"
    assert state.topic.intent == "compute"


def test_topic_inference_file_edit():
    ctx = Context()
    state = ctx.update("写文件 'test.txt' 内容为 hello")

    assert state.topic.primary_topic == "file_edit"
    assert "test.txt" in state.topic.active_entities


def test_token_estimation_and_warning_level():
    ctx = Context(config={"CONTEXT_LIMIT": 100})
    long_input = "x" * 400
    ctx.update(long_input)
    state = ctx.update(long_input)

    assert state.token_stats.usage_pct >= 50
    assert state.token_stats.warning_level in ("high", "critical")


def test_get_returns_dict():
    ctx = Context()
    ctx.update("hello")
    data = ctx.get()

    assert isinstance(data, dict)
    assert "recent_turns" in data
    assert "topic" in data
    assert "token_stats" in data


def test_reset_clears_state():
    ctx = Context()
    ctx.update("hello")
    ctx.reset()
    state = ctx.snapshot()

    assert state.recent_turns == []

    state_after = ctx.update("again")
    assert state_after.recent_turns[0].turn_id == 1


def test_update_with_result_dict():
    ctx = Context()
    ctx.update("what is the weather?")
    state = ctx.update_with_result(
        {"tool_name": "weather", "params": {"city": "Beijing"}, "result_preview": "sunny"}
    )

    latest = state.recent_turns[-1]
    assert latest.role == "tool"
    assert latest.tool_calls is not None
    assert latest.tool_calls[0].tool_name == "weather"


def test_update_with_result_str():
    ctx = Context()
    state = ctx.update_with_result("The weather is sunny.")

    latest = state.recent_turns[-1]
    assert latest.role == "assistant"


def test_update_empty_input():
    ctx = Context()
    state = ctx.update("")

    assert len(state.recent_turns) == 1
    turn = state.recent_turns[0]
    assert turn.role == "user"
    assert turn.content_preview == ""


def test_get_before_update_returns_defaults():
    ctx = Context()
    data = ctx.get()

    assert isinstance(data, dict)
    assert data["recent_turns"] == []
    assert data["topic"]["primary_topic"] is None
    assert data["token_stats"]["warning_level"] == "ok"
    assert data["token_stats"]["usage_pct"] == 0.0


def test_warning_level_ok():
    ctx = Context(config={"CONTEXT_LIMIT": 500})
    state = ctx.update("x" * 20)

    assert state.token_stats.warning_level == "ok"
    assert state.token_stats.usage_pct < 50.0


def test_invalid_context_limit_fallback():
    with pytest.warns(UserWarning, match="Invalid CONTEXT_LIMIT"):
        ctx = Context(config={"CONTEXT_LIMIT": "not-a-number"})

    assert ctx.context_limit == 50_000
    state = ctx.update("hello")
    assert state.token_stats.context_limit == 50_000


def test_invalid_max_recent_turns_fallback():
    with pytest.warns(UserWarning, match="Invalid MAX_RECENT_TURNS"):
        ctx = Context(config={"MAX_RECENT_TURNS": "not-a-number"})

    assert ctx.max_recent_turns == 5


def test_non_positive_max_recent_turns_fallback():
    with pytest.warns(UserWarning, match="MAX_RECENT_TURNS must be positive"):
        ctx = Context(config={"MAX_RECENT_TURNS": -3})

    assert ctx.max_recent_turns == 5


def test_non_positive_context_limit_fallback():
    with pytest.warns(UserWarning, match="CONTEXT_LIMIT must be positive"):
        ctx = Context(config={"CONTEXT_LIMIT": 0})

    assert ctx.context_limit == 50_000
    state = ctx.update("hello")
    assert state.token_stats.context_limit == 50_000


def test_snapshot_deep_copy_isolated():
    ctx = Context()
    ctx.update("hello")

    snap = ctx.snapshot()
    snap.recent_turns.clear()

    assert len(ctx.snapshot().recent_turns) == 1
    assert len(ctx.get()["recent_turns"]) == 1


def test_agent_process_turn_integration():
    from agent import Agent

    class MemoryStub:
        def __init__(self):
            self._data = {}

        def store(self, key, value):
            self._data[key] = value

        def retrieve(self, key):
            return self._data.get(key)

    # Avoid calling the real LLM API during this integration test.
    context = Context()
    memory = MemoryStub()
    agent = Agent(context=context, memory=memory)
    agent.model.complete = lambda prompt: "It will be sunny in Beijing."

    response = agent.process_turn("what is the weather in Beijing")

    assert response
    data = context.get()
    assert isinstance(data, dict)
    assert data["topic"]["primary_topic"] == "weather"
    assert len(data["recent_turns"]) >= 1


def test_context_get_messages_returns_compacted_list():
    ctx = Context(config={"CONTEXT_LIMIT": 100})
    ctx.update("hello")
    messages = ctx.get_messages()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_context_triggers_snip():
    ctx = Context(config={"KEEP_RECENT_MESSAGES": 10})
    for i in range(20):
        ctx.update(f"message {i}")
    assert ctx._state.compression.snip_triggered
    assert len(ctx.get_messages()) <= 11


def test_context_triggers_micro():
    ctx = Context(config={"KEEP_RECENT_TOOL_RESULTS": 3})
    for i in range(5):
        ctx.update_with_result({
            "tool_name": "weather",
            "params": {"city": "Beijing"},
            "result_preview": f"result {i}: " + "x" * 200,
        })
    assert ctx._state.compression.micro_triggered


def test_context_triggers_tool_result_budget():
    ctx = Context(config={"TOOL_RESULT_BUDGET": 200_000})
    ctx.update_with_result({
        "tool_name": "bash",
        "params": {"cmd": "cat big.log"},
        "result_preview": "x" * 300_000,
    })
    assert ctx._state.compression.tool_result_budget_triggered


def test_context_triggers_compact_history():
    ctx = Context(config={"CONTEXT_LIMIT": 500})
    big = "x" * 200
    for i in range(50):
        ctx.update(f"turn {i} {big}")
    assert ctx._state.compression.compact_history_triggered
    assert len(ctx.get_messages()) == 1


def test_context_no_orphan_tool_results_after_compaction():
    from context.utils import _assert_no_orphan_tool_results
    ctx = Context(config={"KEEP_RECENT_MESSAGES": 10})
    for i in range(20):
        ctx.update_with_result({
            "tool_name": "weather",
            "params": {"city": "Beijing"},
            "result_preview": f"result {i}",
        })
    _assert_no_orphan_tool_results(ctx.get_messages())


def test_context_compact_manual():
    ctx = Context(config={"CONTEXT_LIMIT": 5000})
    for i in range(20):
        ctx.update(f"turn {i}")
    assert not ctx._state.compression.compact_history_triggered
    ctx.compact(force=True)
    assert ctx._state.compression.compact_history_triggered
    assert len(ctx.get_messages()) == 1


def test_context_reactive_compact():
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = reactive_compact(messages)
    assert len(result) == 6  # 1 summary + 5 tail


def test_context_turn_id_preserved():
    ctx = Context(config={"KEEP_RECENT_MESSAGES": 10})
    for i in range(20):
        ctx.update(f"message {i}")
    for msg in ctx.get_messages():
        if isinstance(msg.get("content"), str) and not msg["content"].startswith("["):
            assert "_turn_id" in msg


def test_reset_compression_flags():
    ctx = Context(config={"CONTEXT_LIMIT": 1000, "KEEP_RECENT_MESSAGES": 5})
    for i in range(20):
        ctx.update("x" * 100)

    assert ctx._state.compression.snip_triggered
    ctx.reset_compression_flags()
    assert not ctx._state.compression.snip_triggered
    assert not ctx._state.compression.micro_triggered
    assert not ctx._state.compression.compact_history_triggered
    assert ctx._state.compression.compact_history_failures == 0
    assert not ctx._state.compression.compact_history_disabled


def test_reset_compression_flags_resets_breaker():
    ctx = Context()
    ctx._compact_breaker.failures = 3
    ctx.reset_compression_flags()
    assert ctx._compact_breaker.failures == 0


def test_no_compression_when_usage_low():
    ctx = Context()
    ctx.update("short")

    assert not ctx._state.compression.snip_triggered
    assert not ctx._state.compression.micro_triggered
    assert not ctx._state.compression.compact_history_triggered
    assert not ctx._state.compression.tool_result_budget_triggered
