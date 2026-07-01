"""Agent assembly for the team exercise.

This module dynamically assembles an agent from the student modules
(Config, Model, Tool, Skill, Context, Memory, Subagents).  Context and
Memory are injected by loop.py.  If a module is not yet implemented, an
inline stub class is used so the agent can still be instantiated and
exercised.
"""

import os

# Optional dotenv support. If python-dotenv is installed, load .env.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Try to import real implementations from student modules.
# If a module is not yet implemented, fall back to the inline stub.
try:
    from config import Config
except ImportError:
    class Config:  # Stub
        """Configuration stub: reads from environment variables."""

        def __init__(self):
            self._data = dict(os.environ)

        def get(self, key, default=None):
            """Get a configuration value by key."""
            return self._data.get(key, default)


try:
    from models import Model
except ImportError:
    class Model:  # Stub
        """Model stub: loads config and exposes an LLM complete() method."""

        def __init__(self):
            # Load model-specific configuration from the environment.
            self.api_key = os.environ.get("MODEL_API_KEY", "stub-key")
            self.model_name = os.environ.get("MODEL_NAME", "stub-llm")

        def complete(self, prompt: str) -> str:
            """Call the LLM and return raw text output.

            The Model module does not care about routing, memory, or tools.
            It only receives a prompt and returns text.
            """
            return f"[{self.model_name}] {prompt}"


try:
    from tools import Tool
except ImportError:
    class Tool:  # Stub
        """Tool stub: simulates executing an external action."""

        def execute(self, action, params):
            """Execute the requested action with parameters."""
            return f"[STUB] Executed {action} with {params}"


try:
    from skills import Skill
except ImportError:
    class Skill:  # Stub
        """Skill stub: decides whether to answer directly or use a tool."""

        def decide(self, user_input, llm_response, context, memory):
            """Return a decision dict for the agent to act on.

            Decision shape:
            - {"action": "direct", "response": "..."}
            - {"action": "tool", "tool": "name", "params": {...}}
            """
            lowered = user_input.lower()
            if "weather" in lowered or "天气" in lowered:
                return {"action": "tool", "tool": "weather", "params": {"city": "Beijing"}}
            if "calculate" in lowered or "计算" in lowered:
                return {"action": "tool", "tool": "math", "params": {"expression": user_input}}
            return {"action": "direct", "response": llm_response}


try:
    from subagents import Subagent
except ImportError:
    class Subagent:  # Stub
        """Subagent stub: simulates dispatching work to a sub-agent."""

        def dispatch(self, task_description):
            """Dispatch a task to a sub-agent and return a placeholder result."""
            return f"[STUB] Subagent handled task: {task_description}"


class Agent:
    """Dynamically assembled agent.

    Context and Memory are loaded by loop.py and injected into the Agent.
    The remaining modules (Config, Model, Skill, Tool, Subagent) are
    assembled here.  Missing modules are replaced by stub implementations
    so the scaffold runs out of the box while students implement the real
    behavior.
    """

    def __init__(self, context, memory):
        self.context = context
        self.memory = memory
        self.config = Config()
        self.model = Model()
        self.skill = Skill()
        self.tool = Tool()
        self.subagent = Subagent()

    @property
    def name(self):
        """Agent display name (decouples loop.py from agent.config)."""
        return self.config.get("AGENT_NAME", "Agent")

    def _context_enabled(self):
        return self.config.get("ENABLE_CONTEXT", "true").lower() == "true"

    def _memory_enabled(self):
        return self.config.get("ENABLE_MEMORY", "true").lower() == "true"

    def _build_prompt(self, user_input):
        """Build the prompt sent to the model.

        在调用 LLM 之前，先从 memory.json 中检索历史对话记忆和其它存储项，
        并拼接进提示词。仅在 ENABLE_MEMORY=true 时生效。
        """
        if not self._memory_enabled():
            return user_input

        parts = []

        # 1) 通用记忆（除 history 外的其它 key）
        all_keys = getattr(self.memory, "list", lambda: [])()
        for key in all_keys:
            if key == "history":
                continue
            value = self.memory.retrieve(key)
            if value is not None:
                parts.append(f"[Memory: {key}]\n{value}")

        # 2) 历史对话记忆
        history = self.memory.retrieve("history") or []
        if history:
            history_text = "\n".join(
                f"Q: {h['input']}\nA: {h['response']}" for h in history[-3:]
            )
            parts.append(f"[History]\n{history_text}")

        if parts:
            memory_text = "\n\n".join(parts)
            return f"{memory_text}\n\nQ: {user_input}"
        return user_input

    def _remember(self, user_input, response):
        """把本轮 user_input 和 response 写入 memory.json。"""
        history = self.memory.retrieve("history") or []
        history.append({"input": user_input, "response": response})
        self.memory.store("history", history[-10:])

    def process_turn(self, user_input: str) -> str:
        """Run a single turn.

        Flow:
        1. Update context (optional).
        2. Build prompt with optional memory.
        3. Call Model.complete() to get raw LLM text.
        4. Call Skill.decide() to route: direct answer or tool call.
        5. If tool call, execute via Tool.
        6. Store to memory (optional).
        """
        if self._context_enabled():
            self.context.update(user_input)

        prompt = self._build_prompt(user_input)
        llm_response = self.model.complete(prompt)
        decision = self.skill.decide(
            user_input, llm_response, self.context.get(), self.memory
        )

        if decision.get("action") == "tool":
            result = self.tool.execute(decision.get("tool"), decision.get("params"))
        else:
            result = decision.get("response", llm_response)

        if self._memory_enabled():
            self._remember(user_input, result)

        return str(result)
