"""Context compaction layers operating on standard message dict lists."""

from context.adapter import CompactAdapter, RuleBasedCompactAdapter
from context.config import (
    CONTEXT_LIMIT,
    KEEP_RECENT_MESSAGES,
    KEEP_RECENT_TOOL_RESULTS,
    PERSIST_THRESHOLD,
    TOOL_RESULT_BUDGET,
)
from context.utils import (
    _assert_no_orphan_tool_results,
    _is_tool_result_message,
    _message_has_tool_use,
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


def tool_result_budget(
    messages: list[dict], max_bytes: int = TOOL_RESULT_BUDGET
) -> list[dict]:
    """Persist large tool outputs from the last user message to disk."""
    if not messages:
        return messages
    last = messages[-1]
    if last.get("role") != "user" or not isinstance(last.get("content"), list):
        return messages

    blocks = [
        (i, b)
        for i, b in enumerate(last["content"])
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= max_bytes:
        return messages

    ranked = sorted(
        blocks,
        key=lambda p: len(str(p[1].get("content", ""))),
        reverse=True,
    )
    for _, block in ranked:
        if total <= max_bytes:
            break
        content = str(block.get("content", ""))
        if len(content) <= PERSIST_THRESHOLD:
            continue
        tid = block.get("tool_use_id", "unknown")
        block["content"] = persist_large_output(tid, content)
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)

    _assert_no_orphan_tool_results(messages)
    return messages


def snip_compact(
    messages: list[dict], max_messages: int = KEEP_RECENT_MESSAGES
) -> list[dict]:
    """Crop the middle of a long message list, keeping head and tail."""
    if len(messages) <= max_messages:
        return messages

    keep_head, keep_tail = 3, max_messages - 3
    head_end, tail_start = keep_head, len(messages) - keep_tail

    # Head boundary: if last kept head message has tool_use, pull in following tool_results.
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while (
            head_end < len(messages)
            and _is_tool_result_message(messages[head_end])
        ):
            head_end += 1

    # Tail boundary: if cut lands on tool_result, move tail back to keep the tool_use.
    if (
        tail_start > 0
        and tail_start < len(messages)
        and _is_tool_result_message(messages[tail_start])
        and _message_has_tool_use(messages[tail_start - 1])
    ):
        tail_start -= 1

    if head_end >= tail_start:
        _assert_no_orphan_tool_results(messages)
        return messages

    snipped = tail_start - head_end
    result = (
        messages[:head_end]
        + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
        + messages[tail_start:]
    )
    _assert_no_orphan_tool_results(result)
    return result


def reactive_compact(
    messages: list[dict], adapter: CompactAdapter | None = None
) -> list[dict]:
    """Emergency compaction: keep the last 5 raw messages, summarize the rest."""
    adapter = adapter or RuleBasedCompactAdapter()
    tail_start = max(0, len(messages) - 5)

    # Pairing protection: if tail starts on a tool_result, include its tool_use.
    if (
        tail_start > 0
        and tail_start < len(messages)
        and _is_tool_result_message(messages[tail_start])
        and _message_has_tool_use(messages[tail_start - 1])
    ):
        tail_start -= 1

    summary = compact_history(messages[:tail_start], adapter)[0]
    return [summary] + messages[tail_start:]
