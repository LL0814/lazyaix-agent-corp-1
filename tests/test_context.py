"""Unit tests for the Context module."""

import pytest

from context import Context


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
    ctx = Context(config={"CONTEXT_LIMIT": 100})
    state = ctx.update("x" * 100)

    assert state.token_stats.warning_level == "ok"
    assert state.token_stats.usage_pct < 50.0


def test_invalid_context_limit_fallback():
    with pytest.warns(UserWarning, match="Invalid CONTEXT_LIMIT"):
        ctx = Context(config={"CONTEXT_LIMIT": "not-a-number"})

    assert ctx.context_limit == 4000
    state = ctx.update("hello")
    assert state.token_stats.context_limit == 4000


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

    assert ctx.context_limit == 4000
    state = ctx.update("hello")
    assert state.token_stats.context_limit == 4000


def test_tool_turn_contributes_to_token_estimate():
    ctx = Context()
    user_input = "what is the weather?"
    ctx.update(user_input)
    tool_preview = "sunny and 75 degrees"
    state = ctx.update_with_result(
        {"tool_name": "weather", "params": {"city": "Beijing"}, "result_preview": tool_preview}
    )

    expected_chars = len(user_input[:120]) + len(tool_preview[:120])
    expected_tokens = (expected_chars + 3) // 4  # ceil without math import
    assert state.token_stats.estimated_tokens == expected_tokens


def test_agent_process_turn_integration():
    from agent import Agent

    class MemoryStub:
        def __init__(self):
            self._data = {}

        def store(self, key, value):
            self._data[key] = value

        def retrieve(self, key):
            return self._data.get(key)

    context = Context()
    memory = MemoryStub()
    agent = Agent(context=context, memory=memory)

    response = agent.process_turn("what is the weather in Beijing")

    assert response
    data = context.get()
    assert isinstance(data, dict)
    assert data["topic"]["primary_topic"] == "weather"
    assert len(data["recent_turns"]) >= 1


def test_snapshot_deep_copy_isolated():
    ctx = Context()
    ctx.update("hello")

    snap = ctx.snapshot()
    snap.recent_turns.clear()

    assert len(ctx.snapshot().recent_turns) == 1
    assert len(ctx.get()["recent_turns"]) == 1


def test_compression_configuration_defaults():
    ctx = Context()

    assert ctx.preview_length == 120
    assert ctx.safe_turns == 3
    assert ctx.snip_threshold == 50.0
    assert ctx.micro_threshold == 65.0
    assert ctx.collapse_threshold == 80.0
    assert ctx.auto_threshold == 90.0


def test_compression_configuration_overrides():
    ctx = Context(
        config={
            "PREVIEW_LENGTH": 50,
            "SAFE_TURNS": 2,
            "SNIP_THRESHOLD": 55.0,
            "MICRO_THRESHOLD": 70.0,
            "COLLAPSE_THRESHOLD": 85.0,
            "AUTO_THRESHOLD": 95.0,
        }
    )

    assert ctx.preview_length == 50
    assert ctx.safe_turns == 2
    assert ctx.snip_threshold == 55.0
    assert ctx.micro_threshold == 70.0
    assert ctx.collapse_threshold == 85.0
    assert ctx.auto_threshold == 95.0


def test_non_positive_safe_turns_fallback():
    with pytest.warns(UserWarning, match="SAFE_TURNS must be positive"):
        ctx = Context(config={"SAFE_TURNS": 0})

    assert ctx.safe_turns == 3


def test_preview_length_affects_truncation():
    ctx = Context(config={"PREVIEW_LENGTH": 10})
    state = ctx.update("x" * 100)

    assert state.recent_turns[0].content_preview == "x" * 10


def test_make_preview_method():
    ctx = Context(config={"PREVIEW_LENGTH": 7})

    assert ctx._make_preview("hello world") == "hello w"


def test_protected_keywords_constant():
    assert Context._PROTECTED_KEYWORDS == (
        "write_file",
        "edit_file",
        "edit",
        "error",
        "traceback",
    )
