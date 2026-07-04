# Context Four-Layer Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the `context/` module to implement the four-layer compaction strategy from `docs/CONTEXT_COMPACT_PLAN.md`: L3 tool_result_budget → L1 snip_compact → L2 micro_compact → L4 compact_history, plus reactive_compact for emergency prompt-too-long handling.

**Architecture:** Add standalone compaction utility functions (`context/compaction.py`) that operate on standard Anthropic-style message dict lists. Add a `CompactAdapter` protocol (`context/adapter.py`) for LLM-generated summaries, with a rule-based default. Add config constants and helper utilities (`context/config.py`, `context/utils.py`). Refactor `Context` (`context/state.py`) to maintain an internal `_messages` list, convert `TurnSummary` objects to/from message dicts, and run the compaction pipeline on every update. Update `context/models.py` to track the new compaction state. Replace `demo_compression.py` and `tests/test_context.py` to match the new design.

**Tech Stack:** Python 3.11, Pydantic, pytest, uv

## Global Constraints

- Use `uv run pytest` to run tests.
- Use `uv run python -m py_compile <file>` for syntax checks.
- Follow existing project style: type hints, Pydantic models, config dicts passed to `Context.__init__`.
- Do NOT modify `agent.py` or `loop.py` main message flow; `Context` remains injected and `Context.get()`/`Context.get_messages()` remain the public API.
- All compaction functions must preserve `tool_use`/`tool_result` pairing; no orphan tool_result messages allowed after any layer.
- Default `CONTEXT_LIMIT` is 50,000 characters (~12K tokens), not tokens.
- Transcripts are written to `.transcripts/` relative to the working directory.
- Large tool outputs are persisted to `.task_outputs/tool-results/`.

---

## File Structure

### New files

| File | Responsibility |
|------|----------------|
| `context/config.py` | Default configuration constants for compaction thresholds and limits. |
| `context/utils.py` | `estimate_size`, message/block type helpers, tool-pairing checks, transcript persistence. |
| `context/adapter.py` | `CompactAdapter` protocol and `RuleBasedCompactAdapter` default implementation. |
| `context/compaction.py` | Pure functions for L3, L1, L2, L4, and reactive compaction. |
| `tests/test_compaction_utils.py` | Unit tests for utils. |
| `tests/test_compaction_l1_l2_l3.py` | Unit tests for L3, L1, L2 layers and invariants. |
| `tests/test_compaction_l4.py` | Unit tests for L4 compact_history, adapter, failure handling, and circuit breaker. |

### Modified files

| File | Responsibility |
|------|----------------|
| `context/models.py` | Update `CompactEvent.layer` literal, `CompressionState` fields, and `ContextState` if needed. |
| `context/state.py` | Refactor `Context` to maintain `_messages`, run compaction pipeline, expose `get_messages()`. |
| `demo_compression.py` | Update demos to show L3, L1, L2, L4, and reactive compaction behavior. |
| `tests/test_context.py` | Update existing tests for the refactored `Context` behavior. |

---

## Task 1: P0 Infrastructure — Config, Utils, and Tests

**Files:**
- Create: `context/config.py`
- Create: `context/utils.py`
- Create: `tests/test_compaction_utils.py`

**Interfaces:**
- Produces: `context.config` constants (`CONTEXT_LIMIT`, `KEEP_RECENT_TOOL_RESULTS`, `KEEP_RECENT_MESSAGES`, `PERSIST_THRESHOLD`, `TOOL_RESULT_BUDGET`, `MAX_REACTIVE_RETRIES`, `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES`).
- Produces: `context.utils.estimate_size(messages) -> int`.
- Produces: `context.utils._block_type(block) -> str | None`.
- Produces: `context.utils._message_has_tool_use(msg) -> bool`.
- Produces: `context.utils._is_tool_result_message(msg) -> bool`.
- Produces: `context.utils._assert_no_orphan_tool_results(messages) -> None`.
- Produces: `context.utils.write_transcript(messages) -> Path`.

- [ ] **Step 1: Create `context/config.py` with default constants**

```python
"""Default configuration constants for context compaction."""

from pathlib import Path

WORKDIR = Path.cwd()
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

CONTEXT_LIMIT = 50_000
KEEP_RECENT_TOOL_RESULTS = 3
KEEP_RECENT_MESSAGES = 50
PERSIST_THRESHOLD = 30_000
TOOL_RESULT_BUDGET = 200_000
MAX_REACTIVE_RETRIES = 1
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
```

- [ ] **Step 2: Create `context/utils.py` with helpers**

```python
"""Utilities for context compaction."""

import json
import time
from pathlib import Path

from context.config import TOOL_RESULTS_DIR, TRANSCRIPT_DIR


def estimate_size(messages: list[dict]) -> int:
    """Rough token estimate: ~4 characters per token."""
    return len(str(messages)) // 4


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
    """Raise AssertionError if any tool_result lacks a preceding tool_use."""
    for idx, msg in enumerate(messages):
        if _is_tool_result_message(msg):
            assert idx > 0, f"tool_result at index {idx} has no predecessor"
            assert _message_has_tool_use(messages[idx - 1]), (
                f"Orphan tool_result at index {idx}: {messages}"
            )


def write_transcript(messages: list[dict]) -> Path:
    """Persist the full conversation to disk and return the file path."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path


def persist_large_output(tool_use_id: str, output: str) -> str:
    """Persist a large tool output to disk and return a placeholder marker."""
    if len(output) <= 30000:
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
```

- [ ] **Step 3: Write failing tests in `tests/test_compaction_utils.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run:
```bash
uv run pytest tests/test_compaction_utils.py -v
```

Expected: Import errors because `context/config.py` and `context/utils.py` do not exist yet.

- [ ] **Step 5: Verify files compile**

Run:
```bash
uv run python -m py_compile context/config.py context/utils.py
```

Expected: no output (success).

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/test_compaction_utils.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add context/config.py context/utils.py tests/test_compaction_utils.py
git commit -m "feat(context): add compaction config and utility helpers"
```

---

## Task 2: P1 — Adapter, micro_compact, and compact_history

**Files:**
- Create: `context/adapter.py`
- Create: `context/compaction.py`
- Create: `tests/test_compaction_l4.py`
- Modify: `tests/test_compaction_l1_l2_l3.py` (create file, only L2 tests in this task)

**Interfaces:**
- Consumes: `context.utils.estimate_size`, `_assert_no_orphan_tool_results`, `write_transcript`.
- Consumes: `context.config.CONTEXT_LIMIT`, `KEEP_RECENT_TOOL_RESULTS`.
- Produces: `context.adapter.CompactAdapter` protocol.
- Produces: `context.adapter.RuleBasedCompactAdapter.summarize_history(messages) -> str`.
- Produces: `context.compaction.micro_compact(messages, keep_recent=3) -> list[dict]`.
- Produces: `context.compaction.compact_history(messages, adapter) -> list[dict]`.

- [ ] **Step 1: Create `context/adapter.py`**

```python
"""Adapter interface for LLM-based compaction summaries."""

from typing import Protocol


class CompactAdapter(Protocol):
    """Protocol for generating compaction summaries."""

    def summarize_history(self, messages: list[dict]) -> str:
        """Generate a global summary for compact_history / reactive_compact."""
        ...


class RuleBasedCompactAdapter:
    """Rule-based adapter that does not call an LLM.

    Used for tests, demos, and environments without a configured model.
    """

    def summarize_history(self, messages: list[dict]) -> str:
        topics: set[str] = set()
        files: set[str] = set()
        errors: list[str] = []
        tool_names: set[str] = set()
        last_user = ""

        for msg in messages:
            content = msg.get("content", "")
            text = content if isinstance(content, str) else str(content)
            lowered = text.lower()
            if msg.get("role") == "user" and isinstance(content, str):
                last_user = content
            if "weather" in lowered or "天气" in text:
                topics.add("weather")
            if "calculate" in lowered or "计算" in text:
                topics.add("math")
            if "write" in lowered or "edit" in lowered:
                topics.add("file_edit")
            for path in self._extract_quoted(text):
                if "." in path:
                    files.add(path)
            if "error" in lowered or "traceback" in lowered:
                errors.append(text[:200])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_names.add(block.get("name", "unknown"))

        sections = [
            f"Primary Request: {last_user[:200]}",
            f"Topics: {', '.join(topics) or 'none'}",
            f"Tools Used: {', '.join(tool_names) or 'none'}",
            f"Files: {', '.join(files) or 'none'}",
            f"Errors: {'; '.join(errors) or 'none'}",
            "Current State: conversation compressed by rule-based adapter",
        ]
        return "\n".join(sections)

    @staticmethod
    def _extract_quoted(text: str) -> list[str]:
        import re
        return re.findall(r"['\"](.*?)['\"]", text)
```

- [ ] **Step 2: Implement `micro_compact` and `compact_history` in `context/compaction.py`**

```python
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
```

- [ ] **Step 3: Write L2 and L4 tests**

In `tests/test_compaction_l1_l2_l3.py` (L2 section):

```python
"""Tests for L1/L2/L3 compaction layers."""

import pytest

from context.compaction import micro_compact
from context.utils import _assert_no_orphan_tool_results


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
```

In `tests/test_compaction_l4.py`:

```python
"""Tests for L4 compact_history and adapter."""

from context.adapter import RuleBasedCompactAdapter
from context.compaction import compact_history
from context.config import CONTEXT_LIMIT


def test_compact_history_replaces_messages():
    messages = [{"role": "user", "content": "what is the weather?"}]
    result = compact_history(messages)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert result[0]["content"].startswith("[Compacted]")
    assert "_transcript_path" in result[0]


def test_compact_history_adapter_failure_uses_fallback():
    class BrokenAdapter:
        def summarize_history(self, messages):
            raise RuntimeError("boom")

    messages = [{"role": "user", "content": "hello"}]
    result = compact_history(messages, adapter=BrokenAdapter())
    assert "(empty summary)" in result[0]["content"]


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/test_compaction_l1_l2_l3.py tests/test_compaction_l4.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add context/adapter.py context/compaction.py tests/test_compaction_l1_l2_l3.py tests/test_compaction_l4.py
git commit -m "feat(context): add adapter, micro_compact, and compact_history"
```

---

## Task 3: P2 — tool_result_budget and snip_compact

**Files:**
- Modify: `context/compaction.py`
- Modify: `tests/test_compaction_l1_l2_l3.py`

**Interfaces:**
- Consumes: `context.utils.persist_large_output`, `_message_has_tool_use`, `_is_tool_result_message`, `_assert_no_orphan_tool_results`.
- Consumes: `context.config.TOOL_RESULT_BUDGET`, `PERSIST_THRESHOLD`, `KEEP_RECENT_MESSAGES`.
- Produces: `context.compaction.tool_result_budget(messages, max_bytes=200_000) -> list[dict]`.
- Produces: `context.compaction.snip_compact(messages, max_messages=50) -> list[dict]`.

- [ ] **Step 1: Implement `tool_result_budget` and `snip_compact`**

Append to `context/compaction.py`:

```python

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
        return messages

    snipped = tail_start - head_end
    return (
        messages[:head_end]
        + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
        + messages[tail_start:]
    )
```

- [ ] **Step 2: Add L3 and L1 tests**

Append to `tests/test_compaction_l1_l2_l3.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/test_compaction_l1_l2_l3.py tests/test_compaction_l4.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add context/compaction.py tests/test_compaction_l1_l2_l3.py
git commit -m "feat(context): add tool_result_budget and snip_compact"
```

---

## Task 4: P3 — Context Integration, reactive_compact, and Demo

**Files:**
- Modify: `context/models.py`
- Modify: `context/state.py`
- Modify: `context/compaction.py` (add reactive_compact)
- Modify: `demo_compression.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `context.compaction.micro_compact`, `snip_compact`, `tool_result_budget`, `compact_history`.
- Consumes: `context.adapter.RuleBasedCompactAdapter`.
- Produces: `Context.get_messages() -> list[dict]`.
- Produces: `Context.compact(force=False) -> ContextState`.
- Produces: `context.compaction.reactive_compact(messages, adapter) -> list[dict]`.

- [ ] **Step 1: Update `context/models.py`**

Replace `CompactEvent` and `CompressionState` with:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CompactEvent(BaseModel):
    """Record of a single compaction event."""

    timestamp: datetime
    layer: Literal[
        "tool_result_budget",
        "snip",
        "micro",
        "compact_history",
        "reactive",
    ]
    usage_before: int = 0
    usage_after: int = 0
    notes: str = ""


class CompressionState(BaseModel):
    """Tracks which compaction layers have fired and their history."""

    tool_result_budget_triggered: bool = False
    snip_triggered: bool = False
    micro_triggered: bool = False
    compact_history_triggered: bool = False
    compact_history_failures: int = 0
    compact_history_disabled: bool = False
    compact_history_path: str | None = None
    compact_history_summary: str | None = None
    compact_history: list[CompactEvent] = Field(default_factory=list)
```

Keep `TurnSummary`, `TopicState`, `TokenStats`, and `ContextState` unchanged.

- [ ] **Step 2: Refactor `context/state.py`**

Replace the `Context` class with the following (keep imports at top):

```python
"""Context state management for the agent team exercise."""

import re
import warnings
from datetime import datetime
from math import ceil

from context.adapter import RuleBasedCompactAdapter
from context.compaction import (
    compact_history,
    micro_compact,
    snip_compact,
    tool_result_budget,
)
from context.config import (
    CONTEXT_LIMIT,
    KEEP_RECENT_MESSAGES,
    KEEP_RECENT_TOOL_RESULTS,
    TOOL_RESULT_BUDGET,
)
from context.models import (
    CompactEvent,
    CompressionState,
    ContextState,
    ToolCallRecord,
    TokenStats,
    TopicState,
    TurnSummary,
)
from context.utils import estimate_size


class Context:
    """Manages conversation context state with four-layer compaction."""

    _PROTECTED_KEYWORDS = ("write_file", "edit_file", "error", "traceback")

    def __init__(self, config: dict | None = None, compact_adapter=None):
        config = config or {}

        self.context_limit = self._positive_int(config, "CONTEXT_LIMIT", CONTEXT_LIMIT)
        self.max_recent_turns = self._positive_int(config, "MAX_RECENT_TURNS", 5)
        self.preview_length = self._positive_int(config, "PREVIEW_LENGTH", 120)
        self.keep_recent_tool_results = self._positive_int(
            config, "KEEP_RECENT_TOOL_RESULTS", KEEP_RECENT_TOOL_RESULTS
        )
        self.keep_recent_messages = self._positive_int(
            config, "KEEP_RECENT_MESSAGES", KEEP_RECENT_MESSAGES
        )
        self.tool_result_budget = self._positive_int(
            config, "TOOL_RESULT_BUDGET", TOOL_RESULT_BUDGET
        )

        self.compact_adapter = compact_adapter or RuleBasedCompactAdapter()

        self._state = ContextState()
        self._turn_counter = 0
        self._messages: list[dict] = []

    @staticmethod
    def _positive_int(config: dict, key: str, default: int) -> int:
        try:
            value = int(config.get(key, default))
        except (ValueError, TypeError):
            warnings.warn(f"Invalid {key}; falling back to {default}")
            value = default
        if value <= 0:
            warnings.warn(f"{key} must be positive; falling back to {default}")
            value = default
        return value

    def _make_preview(self, text: str) -> str:
        return text[: self.preview_length]

    def _turn_to_message(self, turn: TurnSummary) -> dict:
        """Convert a TurnSummary to a standard message dict."""
        base = {"_turn_id": turn.turn_id}
        if turn.role == "user":
            return {**base, "role": "user", "content": turn.full_content or turn.content_preview}
        if turn.role == "assistant":
            if turn.tool_calls:
                return {
                    **base,
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"{tc.tool_name}_{turn.turn_id}_{idx}",
                            "name": tc.tool_name,
                            "input": tc.params,
                        }
                        for idx, tc in enumerate(turn.tool_calls)
                    ],
                }
            return {**base, "role": "assistant", "content": turn.full_content or turn.content_preview}
        if turn.role == "tool":
            tc = turn.tool_calls[0] if turn.tool_calls else None
            return {
                **base,
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"{tc.tool_name}_{turn.turn_id}_0" if tc else "unknown",
                        "content": turn.full_content or turn.content_preview,
                    }
                ],
            }
        # system or fallback
        return {**base, "role": "system", "content": turn.full_content or turn.content_preview}

    def _message_to_turn(self, msg: dict) -> TurnSummary:
        """Convert a message dict back to a TurnSummary."""
        role = msg.get("role", "user")
        content = msg.get("content")
        if isinstance(content, str):
            text = content
            tool_calls = None
        else:
            # content is a list of blocks
            text = str(content)
            tool_calls = None
            if role == "assistant":
                tool_calls = [
                    ToolCallRecord(
                        tool_name=block.get("name", "unknown"),
                        params=block.get("input", {}),
                        result_preview=None,
                    )
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_use"
                ]
            elif role == "user":
                # tool_result container → treat as tool role
                result_blocks = [
                    block for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_result"
                ]
                if result_blocks:
                    role = "tool"
                    text = result_blocks[0].get("content", "")
                    tool_calls = [
                        ToolCallRecord(
                            tool_name="unknown",
                            params={},
                            result_preview=text,
                        )
                    ]
        return TurnSummary(
            turn_id=msg.get("_turn_id", 0),
            role=role,  # type: ignore[arg-type]
            content_preview=self._make_preview(text),
            full_content=text,
            tool_calls=tool_calls,
            timestamp=datetime.now(),
        )

    def _sync_messages_to_turns(self) -> None:
        """Rebuild recent_turns from the compacted _messages list."""
        self._state.recent_turns = [self._message_to_turn(msg) for msg in self._messages]

    def _compute_token_stats(self) -> TokenStats:
        """Compute current token usage statistics from _messages."""
        estimated_chars = sum(len(str(m)) for m in self._messages)
        estimated_tokens = max(0, ceil(estimated_chars / 4))
        usage_pct = (
            (estimated_tokens / self.context_limit * 100)
            if self.context_limit > 0
            else 0.0
        )
        if usage_pct >= 80.0:
            warning_level = "critical"
        elif usage_pct >= 50.0:
            warning_level = "high"
        else:
            warning_level = "ok"
        return TokenStats(
            estimated_tokens=estimated_tokens,
            context_limit=self.context_limit,
            usage_pct=usage_pct,
            warning_level=warning_level,  # type: ignore[arg-type]
        )

    def _record_event(
        self,
        layer: str,
        usage_before: int,
        usage_after: int,
        notes: str = "",
    ) -> None:
        event = CompactEvent(
            timestamp=datetime.now(),
            layer=layer,  # type: ignore[arg-type]
            usage_before=usage_before,
            usage_after=usage_after,
            notes=notes,
        )
        self._state.compression.compact_history.append(event)

    def _run_compaction(self) -> None:
        """Run the full compaction pipeline on _messages."""
        before = estimate_size(self._messages)
        before_len = len(self._messages)

        self._messages = tool_result_budget(self._messages, self.tool_result_budget)
        after = estimate_size(self._messages)
        if after < before:
            self._state.compression.tool_result_budget_triggered = True
            self._record_event("tool_result_budget", before, after)
            before = after

        self._messages = snip_compact(self._messages, self.keep_recent_messages)
        after = estimate_size(self._messages)
        if len(self._messages) < before_len:
            self._state.compression.snip_triggered = True
            self._record_event("snip", before, after)
            before = after
            before_len = len(self._messages)

        self._messages = micro_compact(self._messages, self.keep_recent_tool_results)
        after = estimate_size(self._messages)
        if after < before:
            self._state.compression.micro_triggered = True
            self._record_event("micro", before, after)
            before = after

        if (
            estimate_size(self._messages) > self.context_limit
            and not self._state.compression.compact_history_disabled
        ):
            path = self._state.compression.compact_history_path
            try:
                self._messages = compact_history(self._messages, self.compact_adapter)
                self._state.compression.compact_history_triggered = True
                self._state.compression.compact_history_failures = 0
                self._state.compression.compact_history_path = self._messages[0].get(
                    "_transcript_path", path
                )
                self._state.compression.compact_history_summary = self._messages[0].get(
                    "content"
                )
                self._record_event(
                    "compact_history",
                    before,
                    estimate_size(self._messages),
                    notes=f"transcript: {self._state.compression.compact_history_path}",
                )
            except Exception:
                self._state.compression.compact_history_failures += 1
                if (
                    self._state.compression.compact_history_failures
                    >= 3
                ):
                    self._state.compression.compact_history_disabled = True

    def _infer_topic(self, user_input: str, turn_id: int) -> TopicState:
        """Infer topic state from user input keywords and quoted entities."""
        lowered = user_input.lower()

        if "weather" in lowered or "天气" in user_input:
            primary_topic = "weather"
            intent = "query"
        elif "calculate" in lowered or "计算" in user_input:
            primary_topic = "math"
            intent = "compute"
        elif "write" in lowered or "写文件" in user_input or "edit" in lowered:
            primary_topic = "file_edit"
            intent = "request"
        else:
            current = self._state.topic
            return TopicState(
                primary_topic=current.primary_topic,
                intent=current.intent,
                active_entities=current.active_entities,
                last_updated_turn=current.last_updated_turn,
            )

        quoted = re.findall(r"['\"](.*?)['\"]", user_input)

        return TopicState(
            primary_topic=primary_topic,
            intent=intent,
            active_entities=quoted,
            last_updated_turn=turn_id,
        )

    def update(self, user_input: str) -> ContextState:
        """Record a user turn and update context state."""
        self._turn_counter += 1

        turn = TurnSummary(
            turn_id=self._turn_counter,
            role="user",
            content_preview=self._make_preview(user_input),
            full_content=user_input,
            timestamp=datetime.now(),
        )
        self._state.recent_turns.append(turn)
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]
        self._messages.append(self._turn_to_message(turn))

        self._state.topic = self._infer_topic(user_input, self._turn_counter)
        self._run_compaction()
        self._sync_messages_to_turns()
        self._state.token_stats = self._compute_token_stats()

        return self._state

    def update_with_result(self, result: dict | str) -> ContextState:
        """Record an assistant or tool result turn and update context state."""
        self._turn_counter += 1

        if isinstance(result, dict):
            result_preview = result.get("result_preview") or str(result)[:self.preview_length]
            full_result = result.get("result_preview") or str(result)
            tool_call = ToolCallRecord(
                tool_name=result.get("tool_name", "unknown"),
                params=result.get("params", {}),
                result_preview=result_preview,
            )
            turn = TurnSummary(
                turn_id=self._turn_counter,
                role="tool",
                content_preview=result_preview,
                full_content=full_result,
                tool_calls=[tool_call],
                timestamp=datetime.now(),
            )
        else:
            text = str(result)
            turn = TurnSummary(
                turn_id=self._turn_counter,
                role="assistant",
                content_preview=self._make_preview(text),
                full_content=text,
                timestamp=datetime.now(),
            )

        self._state.recent_turns.append(turn)
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]
        self._messages.append(self._turn_to_message(turn))

        self._run_compaction()
        self._sync_messages_to_turns()
        self._state.token_stats = self._compute_token_stats()

        return self._state

    def get(self) -> dict:
        """Return the current context state as a JSON-serializable dict."""
        return self._state.model_dump(mode="json")

    def get_messages(self) -> list[dict]:
        """Return the compacted message list suitable for LLM prompting."""
        return list(self._messages)

    def compact(self, force: bool = False) -> ContextState:
        """Manually trigger compact_history."""
        if force or estimate_size(self._messages) > self.context_limit:
            try:
                before = estimate_size(self._messages)
                self._messages = compact_history(self._messages, self.compact_adapter)
                self._state.compression.compact_history_triggered = True
                self._state.compression.compact_history_path = self._messages[0].get(
                    "_transcript_path"
                )
                self._state.compression.compact_history_summary = self._messages[0].get("content")
                self._record_event(
                    "compact_history",
                    before,
                    estimate_size(self._messages),
                    notes=f"manual compact; transcript: {self._state.compression.compact_history_path}",
                )
            except Exception:
                self._state.compression.compact_history_failures += 1
                if self._state.compression.compact_history_failures >= 3:
                    self._state.compression.compact_history_disabled = True
        self._sync_messages_to_turns()
        self._state.token_stats = self._compute_token_stats()
        return self._state

    def reset_compression_flags(self) -> None:
        """Reset compression trigger flags so layers can fire again."""
        self._state.compression.tool_result_budget_triggered = False
        self._state.compression.snip_triggered = False
        self._state.compression.micro_triggered = False
        self._state.compression.compact_history_triggered = False
        self._state.compression.compact_history_failures = 0
        self._state.compression.compact_history_disabled = False

    def reset(self) -> None:
        """Reset the context state."""
        self._state = ContextState()
        self._turn_counter = 0
        self._messages = []

    def snapshot(self) -> ContextState:
        """Return a deep copy of the current context state."""
        return self._state.model_copy(deep=True)
```

- [ ] **Step 3: Add `reactive_compact` to `context/compaction.py`**

Append:

```python

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
```

- [ ] **Step 4: Update `demo_compression.py`**

Replace the file with demos for L3, L1, L2, L4, and reactive:

```python
#!/usr/bin/env python3
"""Context four-layer compaction demo.

Run: uv run python demo_compression.py
"""

from context import Context
from context.compaction import reactive_compact
from context.utils import estimate_size


def show(ctx, label):
    s = ctx.snapshot()
    c = s.compression
    print(f"\n[{label}]")
    print(f"  turns={len(s.recent_turns)}  chars={sum(len(str(m)) for m in ctx.get_messages())}")
    print(
        f"  flags: budget={c.tool_result_budget_triggered} "
        f"snip={c.snip_triggered} micro={c.micro_triggered} "
        f"compact={c.compact_history_triggered}"
    )
    if c.compact_history:
        print(f"  events: {[(e.layer, e.usage_before, e.usage_after) for e in c.compact_history]}")
    for t in s.recent_turns[-6:]:
        preview = (t.content_preview or "")[:40]
        full = "(cleared)" if t.full_content is None else f"({len(t.full_content)} chars)"
        print(f"    [{t.turn_id}] {t.role:9} {preview!r:42} full={full}")


def demo_l3():
    print("\n=== Demo L3: tool_result_budget ===")
    ctx = Context(config={"TOOL_RESULT_BUDGET": 200_000})
    ctx.update_with_result({
        "tool_name": "bash",
        "params": {"cmd": "cat big.log"},
        "result_preview": "x" * 300_000,
    })
    show(ctx, "500KB tool result persisted")


def demo_l1():
    print("\n=== Demo L1: snip_compact ===")
    ctx = Context(config={"KEEP_RECENT_MESSAGES": 50})
    for i in range(100):
        ctx.update(f"message {i}")
    show(ctx, "100 messages snipped to ~50")


def demo_l2():
    print("\n=== Demo L2: micro_compact ===")
    ctx = Context(config={"KEEP_RECENT_TOOL_RESULTS": 3})
    for i in range(5):
        ctx.update_with_result({
            "tool_name": "weather",
            "params": {"city": "Beijing"},
            "result_preview": f"result {i}: " + "x" * 200,
        })
    show(ctx, "older tool results compacted")


def demo_l4():
    print("\n=== Demo L4: compact_history ===")
    ctx = Context(config={"CONTEXT_LIMIT": 1000})
    big = "x" * 500
    for i in range(50):
        ctx.update(f"turn {i} " + big)
    show(ctx, "history compacted to summary")


def demo_reactive():
    print("\n=== Demo reactive_compact ===")
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = reactive_compact(messages)
    print(f"  before: {len(messages)} messages, after: {len(result)} messages")


def main():
    demo_l3()
    demo_l1()
    demo_l2()
    demo_l4()
    demo_reactive()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Update `tests/test_context.py`**

Keep existing basic tests (update_appends_user_turn, topic inference, get, reset, snapshot). Remove or rewrite compression-related tests to match new design. Add:

```python
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
```

- [ ] **Step 6: Run full test suite**

Run:
```bash
uv run pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 7: Run demo**

Run:
```bash
uv run python demo_compression.py
```

Expected: demos run without errors, showing L3/L1/L2/L4/reactive behavior.

- [ ] **Step 8: Commit**

```bash
git add context/models.py context/state.py context/compaction.py demo_compression.py tests/test_context.py
git commit -m "feat(context): integrate compaction pipeline into Context and update demo/tests"
```

---

## Task 5: P4 — Circuit Breaker, Monitoring, and Final Tests

**Files:**
- Modify: `context/compaction.py`
- Modify: `context/state.py`
- Modify: `tests/test_compaction_l4.py`

**Interfaces:**
- Produces: `context.compaction.CompactCircuitBreaker`.
- Produces: `context.compaction.compact_history` respects breaker.

- [ ] **Step 1: Add `CompactCircuitBreaker` to `context/compaction.py`**

Append:

```python

class CompactCircuitBreaker:
    """Open after MAX consecutive failures to avoid burning API credits."""

    def __init__(self, max_failures: int = 3):
        self.failures = 0
        self.max_failures = max_failures

    def call(self, fn, *args, **kwargs):
        if self.failures >= self.max_failures:
            raise RuntimeError(
                f"AutoCompact circuit breaker open: {self.failures} consecutive failures"
            )
        try:
            result = fn(*args, **kwargs)
            self.failures = 0
            return result
        except Exception:
            self.failures += 1
            raise
```

- [ ] **Step 2: Update `compact_history` to use the breaker**

Modify `compact_history` signature and body:

```python
def compact_history(
    messages: list[dict],
    adapter: CompactAdapter | None = None,
    breaker: CompactCircuitBreaker | None = None,
) -> list[dict]:
    adapter = adapter or RuleBasedCompactAdapter()
    if breaker is None:
        breaker = CompactCircuitBreaker()
    transcript_path = write_transcript(messages)
    summary = breaker.call(adapter.summarize_history, messages)
    if not summary:
        summary = "(empty summary)"
    return [{
        "role": "user",
        "content": f"[Compacted]\n\n{summary}",
        "_transcript_path": str(transcript_path),
    }]
```

- [ ] **Step 3: Update `Context` to pass a shared breaker**

In `context/state.py`, initialize a breaker in `__init__`:

```python
from context.compaction import CompactCircuitBreaker
from context.config import MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES

# in __init__:
self._compact_breaker = CompactCircuitBreaker(
    self._positive_int(config, "MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES", MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES)
)
```

Pass `self._compact_breaker` to `compact_history` calls in `_run_compaction` and `compact()`.

- [ ] **Step 4: Add breaker tests**

Append to `tests/test_compaction_l4.py`:

```python
from context.compaction import CompactCircuitBreaker


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

    breaker.call(fail)
    breaker.call(fail)
    breaker.call(succeed)  # reset
    breaker.call(fail)     # should not open yet
    assert breaker.failures == 1
```

- [ ] **Step 5: Run tests**

Run:
```bash
uv run pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add context/compaction.py context/state.py tests/test_compaction_l4.py
git commit -m "feat(context): add compact_history circuit breaker"
```

---

## Self-Review Checklist

Before starting implementation, verify:

1. **Spec coverage:**
   - [x] L3 `tool_result_budget` → Task 3
   - [x] L1 `snip_compact` → Task 3
   - [x] L2 `micro_compact` → Task 2
   - [x] L4 `compact_history` → Task 2
   - [x] `reactive_compact` → Task 4
   - [x] `CompactAdapter` / `RuleBasedCompactAdapter` → Task 2
   - [x] `Context` integration with `_messages` → Task 4
   - [x] Circuit breaker → Task 5
   - [x] Demo and tests → Task 4, Task 5

2. **Placeholder scan:**
   - [x] No "TBD", "TODO", "implement later"
   - [x] No vague "add error handling" steps
   - [x] No "write tests for the above" without code

3. **Type consistency:**
   - [x] `estimate_size(messages: list[dict]) -> int` used everywhere
   - [x] `compact_history` signature consistent across tasks
   - [x] `CompressionState` fields match models.py

4. **Ordering:**
   - [x] L3 → L1 → L2 → L4 order preserved in `_run_compaction`
   - [x] L3 before L2 invariant documented

5. **Backward compatibility:**
   - [x] `agent.py` / `loop.py` not modified
   - [x] `Context.update()` / `Context.get()` still exist
   - [x] New `Context.get_messages()` is additive only

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-02-context-compaction-implementation-plan.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach would you like?
