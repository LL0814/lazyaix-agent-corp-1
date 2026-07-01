"""Subagent coordinator.

Exposes the `Subagent` class used by the main Agent to dispatch synchronous
tasks to specialized workers (researcher, writer).
"""

from .workers import Researcher, Writer


class Subagent:
    """Coordinator that dispatches tasks to synchronous worker agents."""

    def __init__(self):
        self.workers = {
            "researcher": Researcher(),
            "writer": Writer(),
        }

    def dispatch(self, agent_name: str, task_description: str) -> str:
        """Dispatch a task to the named worker and return its result."""
        worker = self.workers.get(agent_name)
        if worker is None:
            return f"[Subagent] Unknown agent: {agent_name}"
        return worker.run(task_description)

    def task(self, name: str, description: str) -> str:
        """Tool-friendly alias for ``dispatch``."""
        return self.dispatch(name, description)
