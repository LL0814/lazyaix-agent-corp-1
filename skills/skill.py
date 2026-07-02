"""Skill router: decides whether to answer directly or use a tool."""


class Skill:
    """Routes between direct answers and tool calls based on user input."""

    def decide(self, user_input, llm_response, context, memory):
        """Return a decision dict for the agent to act on.

        Decision shape:
        - {"action": "direct", "response": "..."}
        - {"action": "tool", "tool": "name", "params": {...}}
        """
        lowered = user_input.lower()

        if "weather" in lowered or "天气" in user_input:
            return {"action": "tool", "tool": "weather", "params": {"city": "Beijing"}}

        if "calculate" in lowered or "计算" in user_input:
            return {"action": "tool", "tool": "math", "params": {"expression": user_input}}

        if "read" in lowered and "file" in lowered:
            # Very naive file path extraction
            words = user_input.replace("'", "").replace('"', "").split()
            path = words[-1] if words else ""
            return {"action": "tool", "tool": "read_file", "params": {"path": path}}

        if "write" in lowered and "file" in lowered:
            # Naive: expects "write file <path> content <content>"
            words = user_input.replace("'", "").replace('"', "").split()
            if len(words) >= 5:
                path = words[2]
                content = " ".join(words[4:])
                return {"action": "tool", "tool": "write_file", "params": {"path": path, "content": content}}

        if "run" in lowered or "执行" in user_input:
            # Naive: expects "run <command>"
            command = user_input.split(" ", 1)[1] if " " in user_input else ""
            return {"action": "tool", "tool": "run_command", "params": {"command": command}}

        return {"action": "direct", "response": llm_response}
