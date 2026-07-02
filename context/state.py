"""Context state management for the agent team exercise."""

import re
import warnings
from datetime import datetime
from math import ceil

from context.models import ContextState, ToolCallRecord, TokenStats, TopicState, TurnSummary


class Context:
    """Manages conversation context state."""

    _PROTECTED_KEYWORDS = ("write_file", "edit_file", "edit", "error", "traceback")

    def __init__(self, config: dict | None = None):
        config = config or {}

        try:
            self.context_limit = int(config.get("CONTEXT_LIMIT", 4000))
        except (ValueError, TypeError):
            warnings.warn("Invalid CONTEXT_LIMIT; falling back to 4000")
            self.context_limit = 4000

        if self.context_limit <= 0:
            warnings.warn("CONTEXT_LIMIT must be positive; falling back to 4000")
            self.context_limit = 4000

        try:
            self.max_recent_turns = int(config.get("MAX_RECENT_TURNS", 5))
        except (ValueError, TypeError):
            warnings.warn("Invalid MAX_RECENT_TURNS; falling back to 5")
            self.max_recent_turns = 5

        if self.max_recent_turns <= 0:
            warnings.warn("MAX_RECENT_TURNS must be positive; falling back to 5")
            self.max_recent_turns = 5

        self.preview_length = int(config.get("PREVIEW_LENGTH", 120))
        self.safe_turns = int(config.get("SAFE_TURNS", 3))
        if self.safe_turns <= 0:
            warnings.warn("SAFE_TURNS must be positive; falling back to 3")
            self.safe_turns = 3

        self.snip_threshold = float(config.get("SNIP_THRESHOLD", 50.0))
        self.micro_threshold = float(config.get("MICRO_THRESHOLD", 65.0))
        self.collapse_threshold = float(config.get("COLLAPSE_THRESHOLD", 80.0))
        self.auto_threshold = float(config.get("AUTO_THRESHOLD", 90.0))

        self._state = ContextState()
        self._turn_counter = 0

    def _make_preview(self, text: str) -> str:
        return text[: self.preview_length]

    def _estimate_tokens(self) -> int:
        """Estimate tokens from recent turns' content previews.

        Each stored turn exposes a truncated content preview (at most 120
        characters), so we sum those lengths and divide by an approximate
        characters-per-token ratio.
        """
        total_chars = sum(len(turn.content_preview) for turn in self._state.recent_turns)
        return ceil(total_chars / 4)

    def _compute_token_stats(self) -> TokenStats:
        """Compute current token usage statistics."""
        estimated = self._estimate_tokens()
        usage_pct = (estimated / self.context_limit * 100) if self.context_limit > 0 else 0.0

        if usage_pct >= 80.0:
            warning_level = "critical"
        elif usage_pct >= 50.0:
            warning_level = "high"
        else:
            warning_level = "ok"

        return TokenStats(
            estimated_tokens=estimated,
            context_limit=self.context_limit,
            usage_pct=usage_pct,
            warning_level=warning_level,
        )

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
            timestamp=datetime.now(),
        )
        self._state.recent_turns.append(turn)
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]

        self._state.topic = self._infer_topic(user_input, self._turn_counter)
        self._state.token_stats = self._compute_token_stats()

        return self._state

    def update_with_result(self, result: dict | str) -> ContextState:
        """Record an assistant or tool result turn and update context state."""
        self._turn_counter += 1

        if isinstance(result, dict):
            tool_name = result.get("tool_name", "tool")
            params = result.get("params", {})
            result_preview = result.get("result_preview")
            if result_preview is None:
                result_preview = self._make_preview(str(result))

            tool_call = ToolCallRecord(
                tool_name=tool_name,
                params=params,
                result_preview=result_preview,
            )
            turn = TurnSummary(
                turn_id=self._turn_counter,
                role="tool",
                content_preview=self._make_preview(result_preview),
                tool_calls=[tool_call],
                timestamp=datetime.now(),
            )
        else:
            text = str(result)
            turn = TurnSummary(
                turn_id=self._turn_counter,
                role="assistant",
                content_preview=self._make_preview(text),
                timestamp=datetime.now(),
            )

        self._state.recent_turns.append(turn)
        self._state.recent_turns = self._state.recent_turns[-self.max_recent_turns :]
        self._state.token_stats = self._compute_token_stats()

        return self._state

    def get(self) -> dict:
        """Return the current context state as a JSON-serializable dict."""
        return self._state.model_dump(mode="json")

    def reset(self) -> None:
        """Reset the context state."""
        self._state = ContextState()
        self._turn_counter = 0

    def snapshot(self) -> ContextState:
        """Return a deep copy of the current context state."""
        return self._state.model_copy(deep=True)
