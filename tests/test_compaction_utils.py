"""Tests for context compaction utilities."""

from context.utils import (
    _assert_no_orphan_tool_results,
    _is_tool_result_message,
    _message_has_tool_use,
    estimate_size,
    persist_large_output,
    write_transcript,
)


def test_estimate_size_empty():
    assert estimate_size([]) == 0


def test_estimate_size_single_message():
    messages = [{"role": "user", "content": "hello world"}]
    assert estimate_size(messages) == len(str(messages)) // 4


def test_message_has_tool_use_true():
    msg = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "tu1", "name": "weather", "input": {"city": "Beijing"}}
        ],
    }
    assert _message_has_tool_use(msg) is True


def test_message_has_tool_use_false_for_user():
    msg = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "sunny"}]}
    assert _message_has_tool_use(msg) is False


def test_is_tool_result_message_true():
    msg = {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "sunny"}],
    }
    assert _is_tool_result_message(msg) is True


def test_assert_no_orphan_tool_results_ok():
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu1", "name": "weather", "input": {}}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "sunny"}],
        },
    ]
    _assert_no_orphan_tool_results(messages)


def test_assert_no_orphan_tool_results_raises():
    messages = [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "sunny"}]},
    ]
    try:
        _assert_no_orphan_tool_results(messages)
    except AssertionError:
        return
    raise AssertionError("expected AssertionError")


def test_write_transcript_creates_file(tmp_path, monkeypatch):
    import context.utils as utils_module
    monkeypatch.setattr(utils_module, "TRANSCRIPT_DIR", tmp_path / ".transcripts")
    messages = [{"role": "user", "content": "hello"}]
    path = write_transcript(messages)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip() == '{"role": "user", "content": "hello"}'


def test_persist_large_output_short_output_unchanged():
    assert persist_large_output("tu1", "short") == "short"


def test_persist_large_output_persists_long_output(tmp_path, monkeypatch):
    import context.utils as utils_module
    monkeypatch.setattr(utils_module, "TOOL_RESULTS_DIR", tmp_path / "tool-results")
    big = "x" * 30001
    result = persist_large_output("tu1", big)
    assert "<persisted-output>" in result
    assert (tmp_path / "tool-results" / "tu1.txt").exists()
