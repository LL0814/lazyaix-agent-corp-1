"""Skill module.

Implements the `Skill` class that decides whether the agent should answer
directly, call a tool, or dispatch a task to a Subagent worker.
"""


class Skill:
    """Route user input to the appropriate action."""

    def decide(self, user_input, llm_response, context, memory):
        """Return a decision dict for the agent to act on.

        Decision shapes:
        - {"action": "direct", "response": "..."}
        - {"action": "tool", "tool": "name", "params": {...}}
        """
        lowered = user_input.lower()

        # Research-oriented tasks go to the researcher subagent.
        if any(kw in lowered for kw in ("研究", "分析", "总结", "复杂", "长", "research", "analyze", "summarize")):
            return {
                "action": "tool",
                "tool": "task",
                "params": {
                    "agent": "researcher",
                    "description": user_input,
                },
            }

        # Writing-oriented tasks go to the writer subagent.
        if any(kw in lowered for kw in ("写", "文章", "文案", "创作", "博客", "write", "blog", "draft")):
            return {
                "action": "tool",
                "tool": "task",
                "params": {
                    "agent": "writer",
                    "description": user_input,
                },
            }

        # Existing placeholder tools.
        if "weather" in lowered or "天气" in lowered:
            return {"action": "tool", "tool": "weather", "params": {"city": "Beijing"}}
        if "calculate" in lowered or "计算" in lowered:
            return {"action": "tool", "tool": "math", "params": {"expression": user_input}}

        return {"action": "direct", "response": llm_response}
