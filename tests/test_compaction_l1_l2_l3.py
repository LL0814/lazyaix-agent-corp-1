"""Tests for L1/L2/L3 compaction layers."""

import pytest

from context.compaction import micro_compact
from context.utils import _assert_no_orphan_tool_results, _is_tool_result_message


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
