"""Unit tests for the Context module."""

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
