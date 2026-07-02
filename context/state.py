"""Context state management for the agent team exercise."""

import re
import warnings
from datetime import datetime
from math import ceil

from context.models import CompactEvent, ContextState, ToolCallRecord, TokenStats, TopicState, TurnSummary


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
        """Estimate tokens from full_content, falling back to content_preview."""
        total = 0
        for turn in self._state.recent_turns:
            text = turn.full_content or turn.content_preview or ""
            total += len(text)
            if turn.tool_calls:
                for tc in turn.tool_calls:
                    preview = tc.result_preview or ""
                    total += len(preview)
        return max(0, ceil(total / 4))

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

    def _is_protected(self, turn: TurnSummary) -> bool:
        """Check if a turn should be protected from snipping."""
        text = turn.full_content or turn.content_preview or ""
        return any(keyword in text for keyword in self._PROTECTED_KEYWORDS)

    def _record_compact_event(
        self,
        layer: str,
        turns_removed: int = 0,
        notes: str = "",
    ) -> None:
        """Record a compression event in the compression state."""
        before = self._state.token_stats.usage_pct
        self._state.token_stats = self._compute_token_stats()
        after = self._state.token_stats.usage_pct
        threshold = getattr(self, f"{layer}_threshold")
        event = CompactEvent(
            timestamp=datetime.now(),
            layer=layer,  # type: ignore[arg-type]
            threshold=threshold,
            usage_before=before,
            usage_after=after,
            turns_removed=turns_removed,
            notes=notes,
        )
        self._state.compression.compact_history.append(event)

    def _snip_compact(self) -> bool:
        """Snip old safe turns to reduce context size.

        Removes turns that are not in the safe window and do not contain
        protected keywords, until usage drops below the snip threshold or
        no more candidates remain.
        """
        if self._state.compression.snip_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.snip_threshold:
            return False

        removed = 0
        while self._state.token_stats.usage_pct >= self.snip_threshold:
            candidates = [
                i
                for i, turn in enumerate(self._state.recent_turns[:-self.safe_turns])
                if not self._is_protected(turn)
            ]
            if not candidates:
                break
            idx = candidates[0]
            self._state.recent_turns.pop(idx)
            removed += 1
            self._state.token_stats = self._compute_token_stats()

        if removed > 0:
            self._state.compression.snip_triggered = True
            self._record_compact_event("snip", removed)
            return True
        return False

    def _micro_compact(self) -> bool:
        """Clear full_content of old tool turns to reduce size.

        Only affects tool turns outside the safe window.
        """
        if self._state.compression.micro_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.micro_threshold:
            return False

        cleared = 0
        for turn in self._state.recent_turns[:-self.safe_turns]:
            if turn.role == "tool" and turn.full_content:
                turn.full_content = None
                cleared += 1

        if cleared > 0:
            self._state.compression.micro_triggered = True
            self._record_compact_event("micro", 0)
            return True
        return False

    def _context_collapse(self) -> bool:
        """Collapse old turns into a single summary turn.

        Combines all turns outside the safe window into one system summary turn.
        """
        if self._state.compression.collapse_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.collapse_threshold:
            return False

        if len(self._state.recent_turns) <= self.safe_turns:
            return False

        old_turns = self._state.recent_turns[:-self.safe_turns]
        kept_turns = self._state.recent_turns[-self.safe_turns:]

        topics = {self._state.topic.primary_topic}
        topics.discard(None)
        entities = list(self._state.topic.active_entities)[:5]

        summary_text = (
            f"[Summary of turns {old_turns[0].turn_id}-{old_turns[-1].turn_id}] "
            f"Topics: {', '.join(topics) or 'none'}. "
            f"Entities: {', '.join(entities) or 'none'}."
        )
        summary_turn = TurnSummary(
            turn_id=old_turns[-1].turn_id,
            role="system",
            content_preview=self._make_preview(summary_text),
            full_content=summary_text,
            timestamp=datetime.now(),
        )

        self._state.recent_turns = [summary_turn] + kept_turns
        self._state.compression.collapse_triggered = True
        self._record_compact_event("collapse", len(old_turns))
        return True

    def _auto_compact(self) -> bool:
        """Auto-compact stub: records event but does not call LLM.

        Real LLM-based compression would be implemented here when a model
        adapter is available.
        """
        if self._state.compression.auto_triggered:
            return False

        usage = self._state.token_stats.usage_pct
        if usage < self.auto_threshold:
            return False

        self._state.compression.auto_triggered = True
        before = self._state.token_stats.usage_pct
        self._state.token_stats = self._compute_token_stats()
        after = self._state.token_stats.usage_pct
        event = CompactEvent(
            timestamp=datetime.now(),
            layer="auto",
            threshold=self.auto_threshold,
            usage_before=before,
            usage_after=after,
            notes="LLM compact not available in stub mode",
        )
        self._state.compression.compact_history.append(event)
        return True

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

        self._state.topic = self._infer_topic(user_input, self._turn_counter)
        self._state.token_stats = self._compute_token_stats()
        self._run_compression()

        return self._state

    def _run_compression(self) -> None:
        """Run compression layers in order after each update."""
        self._state.token_stats = self._compute_token_stats()
        self._snip_compact()
        self._state.token_stats = self._compute_token_stats()
        self._micro_compact()
        self._state.token_stats = self._compute_token_stats()
        self._context_collapse()
        self._state.token_stats = self._compute_token_stats()
        self._auto_compact()
        self._state.token_stats = self._compute_token_stats()

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
        self._state.token_stats = self._compute_token_stats()
        self._run_compression()

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
