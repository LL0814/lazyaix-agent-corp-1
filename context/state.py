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
                    tool_name = self._tool_name_from_tool_use_id(
                        result_blocks[0].get("tool_use_id", "")
                    )
                    tool_calls = [
                        ToolCallRecord(
                            tool_name=tool_name,
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

    @staticmethod
    def _tool_name_from_tool_use_id(tool_use_id: str) -> str:
        """Extract the tool name from a tool_use_id like '{name}_{turn_id}_{idx}'."""
        parts = tool_use_id.split("_")
        if len(parts) >= 3:
            return "_".join(parts[:-2])
        return "unknown"

    def _sync_messages_to_turns(self) -> None:
        """Rebuild recent_turns from the compacted _messages list."""
        self._state.recent_turns = [self._message_to_turn(msg) for msg in self._messages]
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]

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
        if after < before:
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
        pair_id = self._turn_counter

        if isinstance(result, dict):
            tool_name = result.get("tool_name", "unknown")
            params = result.get("params", {})
            result_preview = result.get("result_preview") or str(result)[:self.preview_length]
            full_result = result.get("result_preview") or str(result)

            # Record the assistant tool_use first to preserve pairing.
            assistant_turn = TurnSummary(
                turn_id=pair_id,
                role="assistant",
                content_preview="",
                full_content=None,
                tool_calls=[
                    ToolCallRecord(
                        tool_name=tool_name,
                        params=params,
                        result_preview=None,
                    )
                ],
                timestamp=datetime.now(),
            )
            self._state.recent_turns.append(assistant_turn)
            self._messages.append(self._turn_to_message(assistant_turn))

            tool_call = ToolCallRecord(
                tool_name=tool_name,
                params=params,
                result_preview=result_preview,
            )
            turn = TurnSummary(
                turn_id=pair_id,
                role="tool",
                content_preview=result_preview,
                full_content=full_result,
                tool_calls=[tool_call],
                timestamp=datetime.now(),
            )
        else:
            text = str(result)
            turn = TurnSummary(
                turn_id=pair_id,
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
