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
    from config.env import load_env_file

    load_env_file()


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
        # 通用 Skill 路由：注入 model 启用 LLM 意图识别，
        # LLM 不可用时自动回退到关键词规则匹配。
        try:
            self.skill = Skill(model=self.model)
        except TypeError:
            # 兼容旧版 Skill 签名（无 model 参数）
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

        Memory and compacted context history are included when enabled.
        """
        parts = []

        if self._memory_enabled():
            summary_memory = self._retrieve_summary_memory()
            if summary_memory:
                parts.append(summary_memory)

            long_term_memory = self._retrieve_long_term_memories(user_input)
            if long_term_memory:
                parts.append(long_term_memory)

            history = self.memory.retrieve("history") or []
            memory_text = "\n".join(
                f"Q: {h['input']}\nA: {h['response']}" for h in history[-3:]
                if not self._is_memory_recall_meta_input(str(h.get("input", "")))
            )
            if memory_text:
                parts.append(memory_text)

        if self._context_enabled():
            messages = self.context.get_messages()
            if messages:
                context_text = "\n".join(
                    f"{m.get('role', 'user')}: {m.get('content', '')}"
                    for m in messages
                )
                parts.append(f"Conversation history:\n{context_text}")

        parts.append(f"Q: {user_input}")
        return "\n\n".join(parts)

    def _retrieve_summary_memory(self):
        if not hasattr(self.memory, "get_summary"):
            return ""
        try:
            summary = self.memory.get_summary()
        except Exception:
            return ""
        if not summary:
            return ""
        return f"Memory summary:\n{summary}"

    def _retrieve_long_term_memories(self, user_input):
        if not hasattr(self.memory, "search") or not hasattr(self.memory, "debug_counts"):
            return ""
        try:
            counts = self.memory.debug_counts()
            if getattr(counts, "records", 0) <= 0:
                return ""
            top_k = int(self.config.get("MEMORY_PROMPT_TOP_K", "12"))
            results = self.memory.search(user_input, top_k=top_k)
        except Exception:
            return ""
        if not results:
            return ""
        lines = [f"- [{result.kind.value}] {result.content}" for result in results]
        return "Long-term memories:\n" + "\n".join(lines)

    @staticmethod
    def _is_memory_recall_meta_input(user_input):
        patterns = (
            "基于长期记忆",
            "根据长期记忆",
            "根据你的长期记忆",
            "长期记忆中",
            "你还记得",
            "你记得",
            "还记得我",
        )
        return any(pattern in user_input for pattern in patterns) and (
            "请记住" not in user_input and "记为" not in user_input
        )

    def _remember(self, user_input, response):
        """Store the turn in memory when ENABLE_MEMORY is true."""
        history = self.memory.retrieve("history") or []
        history.append({"input": user_input, "response": response})
        self.memory.store("history", history[-10:])
        self._process_memory_outbox()

    def _process_memory_outbox(self):
        if not hasattr(self.memory, "process_outbox"):
            return
        config = getattr(self.memory, "config", None)
        auto_process = getattr(config, "auto_process_outbox", True)
        if not auto_process:
            return
        limit = int(self.config.get("MEMORY_WORKER_LIMIT", "10"))
        try:
            self.memory.process_outbox(limit=limit)
        except Exception:
            return

    def process_turn(self, user_input: str) -> str:
        """Run a single turn.

        Flow:
        1. Update context (optional).
        2. Build prompt with optional memory and compacted context.
        3. Call Model.complete() to get raw LLM text.
        4. Call Skill.decide() to route: direct answer or tool call.
        5. If tool call, execute via Tool and record the result in context.
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
            if self._context_enabled():
                self.context.update_with_result({
                    "tool_name": decision.get("tool", "unknown"),
                    "params": decision.get("params", {}),
                    "result_preview": str(result),
                })
        else:
            result = decision.get("response", llm_response)

        if self._memory_enabled():
            self._remember(user_input, result)

        return str(result)
