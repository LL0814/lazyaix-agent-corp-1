"""Subagent workers.

This module defines lightweight synchronous workers that can be dispatched
by the main Subagent coordinator. Each worker exposes a single `run()`
entry point and returns a string result.

When a `model` instance is provided, workers call `model.complete(prompt)`
to generate results via an LLM; otherwise they fall back to a formatted
placeholder string.
"""


class Researcher:
    """Worker for research, analysis, and summarization tasks."""

    def __init__(self, model=None):
        self.model = model

    def run(self, description: str) -> str:
        """Run a research task and return a formatted result."""
        if self.model is None:
            return f"[Researcher] Completed research: {description}"
        prompt = (
            "You are a research assistant. Please research and summarize "
            "the following topic concisely:\n\n"
            f"{description}"
        )
        result = self.model.complete(prompt)
        return f"[Researcher] Completed research: {result}"


class Writer:
    """Worker for writing, copywriting, and content generation tasks."""

    def __init__(self, model=None):
        self.model = model

    def run(self, description: str) -> str:
        """Run a writing task and return a formatted result."""
        if self.model is None:
            return f"[Writer] Completed writing task: {description}"
        prompt = (
            "You are a writing assistant. Please write content based on "
            "the following request:\n\n"
            f"{description}"
        )
        result = self.model.complete(prompt)
        return f"[Writer] Completed writing task: {result}"
