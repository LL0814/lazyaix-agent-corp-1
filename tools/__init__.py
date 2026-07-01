"""Tool module.

Implements the `Tool` class used by the main Agent to execute external
actions. Registers a built-in `task` action that forwards work to the
Subagent coordinator.
"""

try:
    from subagents import Subagent
except ImportError:  # pragma: no cover - stub fallback
    class Subagent:
        """Stub Subagent used when the real module is not available."""

        def dispatch(self, agent_name: str, task_description: str) -> str:
            return f"[STUB] Subagent handled task: {task_description}"


class Tool:
    """Tool executor with a built-in `task` action for Subagent dispatch."""

    def __init__(self):
        self.subagent = Subagent()

    def execute(self, action, params):
        """Execute the requested action with parameters.

        Supported actions:
        - "task": dispatch to a Subagent worker.
          params: {"agent": "researcher|writer", "description": "..."}
        - "weather": placeholder weather lookup.
        - "math": placeholder math evaluation.
        """
        if action == "task":
            return self.subagent.dispatch(
                params.get("agent"), params.get("description", "")
            )
        if action == "weather":
            return f"[Tool] Weather in {params.get('city', 'Unknown')} is sunny."
        if action == "math":
            return f"[Tool] Math result for {params.get('expression', '')}"
        return f"[Tool] Executed {action} with {params}"
