"""Adapter interface for LLM-based compaction summaries."""

import re
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
        return re.findall(r"['\"](.*?)['\"]", text)
