"""Subagent workers.

This module defines lightweight synchronous workers that can be dispatched
by the main Subagent coordinator. Each worker exposes a single `run()`
entry point and returns a string result.
"""


class Researcher:
    """Worker for research, analysis, and summarization tasks."""

    def run(self, description: str) -> str:
        """Run a research task and return a formatted result."""
        return f"[Researcher] Completed research: {description}"


class Writer:
    """Worker for writing, copywriting, and content generation tasks."""

    def run(self, description: str) -> str:
        """Run a writing task and return a formatted result."""
        return f"[Writer] Completed writing task: {description}"
