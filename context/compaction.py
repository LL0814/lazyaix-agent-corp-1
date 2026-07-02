"""Context compaction layers operating on standard message dict lists."""

from context.adapter import CompactAdapter, RuleBasedCompactAdapter
from context.config import (
    CONTEXT_LIMIT,
    KEEP_RECENT_TOOL_RESULTS,
    PERSIST_THRESHOLD,
    TOOL_RESULT_BUDGET,
)
from context.utils import (
    _assert_no_orphan_tool_results,
    _is_tool_result_message,
    estimate_size,
    persist_large_output,
    write_transcript,
)


def _collect_tool_result_blocks(messages: list[dict]):
    """Collect all tool_result blocks with their (msg_idx, block_idx, block)."""
    blocks = []
    for msg_idx, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block_idx, block in enumerate(msg["content"]):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append((msg_idx, block_idx, block))
    return blocks


def micro_compact(messages: list[dict], keep_recent: int = KEEP_RECENT_TOOL_RESULTS) -> list[dict]:
    """Replace older large tool_result contents with placeholders.

    Keeps the ``keep_recent`` most recent tool_result blocks intact.
    """
    tool_results = _collect_tool_result_blocks(messages)
    if len(tool_results) <= keep_recent:
        return messages
    for _, _, block in tool_results[:-keep_recent]:
        content = block.get("content", "")
        text = content if isinstance(content, str) else str(content)
        if len(text) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    _assert_no_orphan_tool_results(messages)
    return messages


def compact_history(messages: list[dict], adapter: CompactAdapter | None = None) -> list[dict]:
    """Persist the full transcript and replace all messages with a summary."""
    adapter = adapter or RuleBasedCompactAdapter()
    transcript_path = write_transcript(messages)
    try:
        summary = adapter.summarize_history(messages)
    except Exception:
        summary = "(empty summary)"
    return [{
        "role": "user",
        "content": f"[Compacted]\n\n{summary}",
        "_transcript_path": str(transcript_path),
    }]
