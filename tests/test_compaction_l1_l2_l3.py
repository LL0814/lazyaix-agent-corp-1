"""Tests for L1/L2/L3 compaction layers."""

import pytest

from context.compaction import micro_compact
from context.utils import _assert_no_orphan_tool_results, _is_tool_result_message, _message_has_tool_use


def _tool_use_msg(tool_use_id, name="weather"):
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": tool_use_id, "name": name, "input": {"city": "Beijing"}}
        ],
    }


def _tool_result_msg(tool_use_id, content):
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
    }


def test_micro_compact_keeps_recent_3():
    messages = []
    for i in range(5):
        messages.append(_tool_use_msg(f"tu{i}"))
        messages.append(_tool_result_msg(f"tu{i}", f"result {i} " + "x" * 200))
    compacted = micro_compact(messages, keep_recent=3)
    _assert_no_orphan_tool_results(compacted)
    # First 2 tool_results should be compacted, last 3 kept
    assert "compacted" in compacted[1]["content"][0]["content"]
    assert "compacted" in compacted[3]["content"][0]["content"]
    assert "result 2" in compacted[5]["content"][0]["content"]
    assert "result 3" in compacted[7]["content"][0]["content"]
    assert "result 4" in compacted[9]["content"][0]["content"]


def test_micro_compact_skips_short_results():
    messages = [
        _tool_use_msg("tu0"),
        _tool_result_msg("tu0", "short"),
        _tool_use_msg("tu1"),
        _tool_result_msg("tu1", "short"),
        _tool_use_msg("tu2"),
        _tool_result_msg("tu2", "short"),
        _tool_use_msg("tu3"),
        _tool_result_msg("tu3", "short"),
    ]
    compacted = micro_compact(messages, keep_recent=3)
    for msg in compacted:
        if _is_tool_result_message(msg):
            assert msg["content"][0]["content"] == "short"


def test_micro_compact_no_op_when_few_results():
    messages = [
        _tool_use_msg("tu0"),
        _tool_result_msg("tu0", "x" * 200),
    ]
    compacted = micro_compact(messages, keep_recent=3)
    assert "x" * 200 in compacted[1]["content"][0]["content"]


from context.compaction import snip_compact, tool_result_budget


def test_tool_result_budget_persists_large_output(tmp_path, monkeypatch):
    import context.utils as utils_module
    monkeypatch.setattr(utils_module, "TOOL_RESULTS_DIR", tmp_path / "tool-results")
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu1", "name": "bash", "input": {"cmd": "cat big"}}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "x" * 300_000}],
        },
    ]
    result = tool_result_budget(messages, max_bytes=200_000)
    _assert_no_orphan_tool_results(result)
    assert "<persisted-output>" in result[-1]["content"][0]["content"]


def test_tool_result_budget_no_op_under_budget():
    messages = [
        _tool_use_msg("tu1"),
        _tool_result_msg("tu1", "small result"),
    ]
    result = tool_result_budget(messages, max_bytes=200_000)
    assert result[-1]["content"][0]["content"] == "small result"


def test_snip_compact_crops_middle():
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(100)]
    result = snip_compact(messages, max_messages=50)
    assert len(result) == 51
    assert result[0]["content"] == "msg 0"
    assert result[2]["content"] == "msg 2"
    assert "[snipped" in result[3]["content"]
    assert result[4]["content"] == "msg 53"
    assert result[-1]["content"] == "msg 99"


def test_snip_compact_protects_tool_pair_head():
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(60)]
    # Insert tool_use at index 2, tool_result at index 3
    messages[2] = _tool_use_msg("tu1")
    messages[3] = _tool_result_msg("tu1", "sunny")
    result = snip_compact(messages, max_messages=50)
    _assert_no_orphan_tool_results(result)
    # The tool_result at index 3 should be pulled into head if needed
    ids = [m.get("_test_id") for m in result]
    # Instead verify no orphan and structure
    assert any(_message_has_tool_use(m) for m in result)


def test_snip_compact_no_op_when_short():
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    result = snip_compact(messages, max_messages=50)
    assert len(result) == 10
