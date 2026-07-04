"""Utilities for context compaction."""

import json
import uuid
import warnings
from pathlib import Path

from context.config import PERSIST_THRESHOLD, TOOL_RESULTS_DIR, TRANSCRIPT_DIR


def estimate_size(messages: list[dict]) -> int:
    """Return the total character count of the messages list."""
    if not messages:
        return 0
    return len(str(messages))


def _block_type(block) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _message_has_tool_use(msg: dict) -> bool:
    """Return True if the message contains a tool_use block."""
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(_block_type(b) == "tool_use" for b in content)


def _is_tool_result_message(msg: dict) -> bool:
    """Return True if the message is a tool_result container."""
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _assert_no_orphan_tool_results(messages: list[dict]) -> None:
    """Raise RuntimeError if any tool_result lacks a preceding tool_use."""
    for idx, msg in enumerate(messages):
        if _is_tool_result_message(msg):
            if idx == 0:
                raise RuntimeError(f"tool_result at index {idx} has no predecessor")
            if not _message_has_tool_use(messages[idx - 1]):
                raise RuntimeError(f"Orphan tool_result at index {idx}: {messages}")


def write_transcript(messages: list[dict]) -> Path:
    """Persist the full conversation to disk and return the file path."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{uuid.uuid4().hex}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path


def persist_large_output(tool_use_id: str, output: str) -> str:
    """Persist a large tool output to disk and return a placeholder marker."""
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output, encoding="utf-8")
    return (
        f"<persisted-output>\n"
        f"Full output: {path}\n"
        f"Preview:\n{output[:2000]}\n"
        f"</persisted-output>"
    )
