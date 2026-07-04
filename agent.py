"""Agent assembly for the team exercise.

This module dynamically assembles an agent from the student modules
(Config, Model, Tool, Skill, Context, Memory, Subagents).  Context and
Memory are injected by loop.py.  If a module is not yet implemented, an
inline stub class is used so the agent can still be instantiated and
exercised.
"""

import os
from collections.abc import Iterator

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

        def stream_complete(self, prompt: str):
            """Stream the LLM response."""
            yield self.complete(prompt)


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


try:
    from girlfriend import GirlfriendEngine
except ImportError:
    GirlfriendEngine = None


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
        self.girlfriend = (
            GirlfriendEngine()
            if GirlfriendEngine is not None and self._girlfriend_enabled()
            else None
        )

    @property
    def name(self):
        """Agent display name (decouples loop.py from agent.config)."""
        return self.config.get("AGENT_NAME", "Agent")

    def _context_enabled(self):
        return self.config.get("ENABLE_CONTEXT", "true").lower() == "true"

    def _memory_enabled(self):
        return self.config.get("ENABLE_MEMORY", "true").lower() == "true"

    def _streaming_enabled(self):
        return self.config.get("ENABLE_STREAMING", "true").lower() == "true"

    def _vector_memory_enabled(self):
        return self.config.get("ENABLE_VECTOR_MEMORY", "true").lower() == "true"

    def _girlfriend_enabled(self):
        return self.config.get("ENABLE_GIRLFRIEND_MODE", "true").lower() == "true"

    def _build_prompt(self, user_input, vector_memories=None):
        """Build the prompt sent to the model.

        在调用 LLM 之前，先从 memory.json 中检索结构化偏好记忆，
        并以长期记忆说明的形式拼接进提示词。仅在 ENABLE_MEMORY=true 时生效。
        """
        memory_items = []

        if self._memory_enabled():
            all_keys = getattr(self.memory, "list", lambda: [])()
            for key in all_keys:
                if key == "history":
                    continue
                value = self.memory.retrieve(key)
                if value is not None:
                    memory_items.append(f"- {key}: {value}")

        vector_items = self._format_vector_memories(vector_memories or [])
        if memory_items or vector_items:
            sections = [
                "以下是系统检索到的记忆，不是本轮上下文对话记录。",
                "这些记忆只用于理解用户偏好和历史背景；只有和当前问题相关时才参考。",
                "不要主动复述无关记忆，不要因为看到记忆就说“记住了”。",
            ]
            if memory_items:
                sections.append("\n长期结构化记忆/用户画像：")
                sections.extend(memory_items)
            if vector_items:
                sections.append("\n相关历史对话检索结果：")
                sections.extend(vector_items)
            base_prompt = (
                "\n".join(sections)
                + "\n\n"
                f"用户本轮输入：{user_input}"
            )
        else:
            base_prompt = user_input
        return self._apply_girlfriend_prompt(user_input, base_prompt)

    def _apply_girlfriend_prompt(self, user_input, base_prompt):
        if self.girlfriend is None:
            return base_prompt
        return self.girlfriend.build_prompt(user_input, base_prompt)

    def _format_vector_memories(self, vector_memories):
        max_chars = int(self.config.get("VECTOR_MEMORY_MAX_CHARS", "800"))
        items = []
        for index, memory in enumerate(vector_memories, start=1):
            text = str(memory.get("text") or "").strip()
            if not text:
                continue
            if len(text) > max_chars:
                text = f"{text[:max_chars]}..."
            score = memory.get("score")
            prefix = f"{index}. "
            if isinstance(score, (float, int)):
                prefix += f"(score={float(score):.3f}) "
            items.append(f"{prefix}{text}")
        return items

    def _remember(self, user_input, response):
        """只把用户偏好等结构化信息写入 memory.json。

        例如：用户说"我喜欢吃苹果"，会解析并存储为
        {"like": "吃苹果，吃栗子，吃香蕉"}。
        """
        if not self._memory_enabled():
            return
        remember = getattr(self.memory, "remember", None)
        if callable(remember):
            remember(user_input)
        remember_conversation = getattr(self.memory, "remember_conversation", None)
        if callable(remember_conversation):
            remember_conversation(user_input, str(response))

    def _after_turn(self, user_input, response):
        self._remember(user_input, response)
        if self.girlfriend is not None:
            self.girlfriend.update_after_turn(user_input, str(response))

    def girlfriend_follow_ups(self, user_input, response):
        if self.girlfriend is None:
            return []
        return self.girlfriend.follow_up_messages(user_input, str(response))

    def is_emotional_turn(self, user_input):
        if self.girlfriend is None:
            return False
        return self.girlfriend.context_kind(user_input) == "emotional"

    def _search_conversation_memories(self, user_input):
        """Search vector memory with the raw user input before prompt building."""
        if not self._memory_enabled() or not self._vector_memory_enabled():
            return []
        search = getattr(self.memory, "search_conversations", None)
        if not callable(search):
            return []
        try:
            return search(user_input)
        except Exception:  # noqa: BLE001
            return []

    def _precheck_tool_decision(self, user_input):
        """Try tool routing before streaming model text."""
        try:
            decision = self.skill.decide(
                user_input,
                "",
                self.context.get(),
                self.memory,
            )
        except Exception:  # noqa: BLE001
            return None
        if decision.get("action") == "tool":
            return decision
        return None

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

        vector_memories = self._search_conversation_memories(user_input)
        prompt = self._build_prompt(user_input, vector_memories)
        llm_response = self.model.complete(prompt)
        decision = self.skill.decide(
            user_input, llm_response, self.context.get(), self.memory
        )

        if decision.get("action") == "tool":
            result = self.tool.execute(decision.get("tool"), decision.get("params"))
        else:
            result = decision.get("response", llm_response)

        self._after_turn(user_input, result)

        return str(result)

    def process_turn_stream(self, user_input: str) -> Iterator[str]:
        """Run a single turn and stream direct model output."""
        if not self._streaming_enabled():
            yield self.process_turn(user_input)
            return

        if self._context_enabled():
            self.context.update(user_input)

        vector_memories = self._search_conversation_memories(user_input)
        tool_decision = self._precheck_tool_decision(user_input)
        if tool_decision is not None:
            result = self.tool.execute(
                tool_decision.get("tool"),
                tool_decision.get("params"),
            )
            self._after_turn(user_input, result)
            yield str(result)
            return

        prompt = self._build_prompt(user_input, vector_memories)
        stream_complete = getattr(self.model, "stream_complete", None)
        chunks = []
        if callable(stream_complete):
            for chunk in stream_complete(prompt):
                text = str(chunk)
                chunks.append(text)
                yield text
        else:
            text = self.model.complete(prompt)
            chunks.append(text)
            yield text

        response = "".join(chunks)
        self._after_turn(user_input, response)
