"""Real Tool implementations for the agent team exercise."""

import os
import re


class Tool:
    """Executes external actions requested by the Skill router."""

    def execute(self, action, params):
        """Execute the requested action with parameters."""
        handler = getattr(self, f"_{action}", None)
        if handler:
            return handler(params)
        return f"[ERROR] Unknown tool: {action}"

    def _weather(self, params):
        """Return mock weather data."""
        city = params.get("city", "Unknown")
        return f"[Weather Mock] {city}: sunny, 25°C"

    def _math(self, params):
        """Evaluate a simple math expression safely."""
        expression = params.get("expression", "")
        try:
            # Only allow numbers and basic operators
            safe_expr = re.sub(r"[^0-9+\-*/(). ]", "", expression)
            if not safe_expr:
                return "[ERROR] Invalid math expression"
            result = eval(safe_expr)  # noqa: S307
            return f"[Math] {safe_expr} = {result}"
        except Exception as e:
            return f"[ERROR] Math evaluation failed: {e}"

    def _read_file(self, params):
        """Read a file's contents."""
        path = params.get("path", "")
        if not path:
            return "[ERROR] No path provided"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"[ERROR] Could not read {path}: {e}"

    def _write_file(self, params):
        """Write content to a file."""
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return "[ERROR] No path provided"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[Write File] Wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"[ERROR] Could not write {path}: {e}"

    def _run_command(self, params):
        """Run a shell command and return output."""
        command = params.get("command", "")
        if not command:
            return "[ERROR] No command provided"
        try:
            result = os.popen(command).read()
            return f"[Command Output]\n{result}"
        except Exception as e:
            return f"[ERROR] Command failed: {e}"
