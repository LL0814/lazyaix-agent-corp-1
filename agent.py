"""Agent assembly for the team exercise.

This module dynamically assembles an agent from the student modules
(Config, Model, Tool, Skill, Context, Memory, Subagents).  Context and
Memory are injected by loop.py.  If a module is not yet implemented, an
inline stub class is used so the agent can still be instantiated and
exercised.
"""

import logging
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


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
            # Stub: real models.Model is used when available.
            self.api_key = ""
            self.model_name = os.environ.get("MODEL", "stub-llm")

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
    from skills.common import formatter
except ImportError:
    formatter = None


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

    def __init__(self, context, memory, model=None):
        self.context = context
        self.memory = memory
        self.config = Config()
        self.model = model if model is not None else Model()
        self.skill = Skill(model=self.model)
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

        Prefers Context summary + recent turns when Context is enabled and
        supports it; otherwise falls back to Memory history.
        """
        if self._context_enabled() and hasattr(self.context, "get"):
            return self._build_context_prompt(user_input)
        return self._build_memory_prompt(user_input)

    def _build_context_prompt(self, user_input):
        """Build prompt from Context summary and recent turns.

        The most recent turn is the current user input, so it is excluded from
        the historical turns and appended explicitly at the end.
        """
        state = self.context.get()
        parts = []
        summary = state.get("summary", "")
        if summary:
            parts.append(f"对话摘要：\n{summary}")
        # Exclude the latest turn (current user input) from history.
        previous_turns = state.get("turns", [])[:-1]
        for turn in previous_turns[-3:]:
            role = "用户" if turn["role"] == "user" else "助手"
            parts.append(f"{role}：{turn['content']}")
        parts.append(f"用户：{user_input}")
        return "\n".join(parts)

    def _build_memory_prompt(self, user_input):
        """Build prompt from Memory history (legacy fallback)."""
        if not self._memory_enabled():
            return user_input
        history = self.memory.retrieve("history") or []
        memory_text = "\n".join(
            f"Q: {h['input']}\nA: {h['response']}" for h in history[-3:]
        )
        if memory_text:
            return f"{memory_text}\nQ: {user_input}"
        return user_input

    def _format_tool_result(self, result) -> str:
        """Format tool results for human-readable output."""
        if isinstance(result, dict) and "error" in result:
            return f"工具返回错误: {result['error']}"
        if formatter is not None:
            if hasattr(result, "days") and hasattr(result, "destination"):
                return formatter.format_itinerary(result)
        return str(result)

    def _remember(self, user_input, response):
        """Store the turn in memory when ENABLE_MEMORY is true."""
        history = self.memory.retrieve("history") or []
        history.append({"input": user_input, "response": response})
        self.memory.store("history", history[-10:])

    _MODEL_ERROR_PATTERN = re.compile(r"^\[\w+\]")

    def _is_model_error_response(self, response: str) -> bool:
        """Detect provider-formatted error messages from Model.complete().

        All providers return errors wrapped as ``[{provider}] ...`` so that
        Agent can distinguish them from real LLM output.
        """
        return isinstance(response, str) and bool(self._MODEL_ERROR_PATTERN.match(response))

    def _maybe_summarize_context(self):
        """Trigger context summarization if the context supports it and conditions are met."""
        if not hasattr(self.context, "should_summarize"):
            return
        if not self.context.should_summarize():
            return

        def summarizer(prompt: str) -> str:
            resp = self.model.complete(prompt)
            if self._is_model_error_response(resp):
                return ""
            return resp

        self.context.summarize(summarizer)

    def _itinerary_summary(self, itinerary) -> str:
        """Build a short summary string for an itinerary object."""
        dest = getattr(itinerary, "destination", "")
        days = getattr(itinerary, "days", "")
        if dest and days:
            return f"{dest} {days}天行程"
        return "已生成行程"

    def _maybe_set_itinerary(self, tool_name: str, result):
        """Store the generated itinerary in context, offloading to memory if large."""
        if tool_name != "generate_itinerary":
            return
        if not self._context_enabled():
            return
        if not hasattr(self.context, "set_itinerary"):
            return
        if isinstance(result, dict) and "error" in result:
            return
        summary = self._itinerary_summary(result)
        self.context.set_itinerary(result, memory=self.memory, summary=summary)

    def _reset_state(self):
        """Reset Context and Memory when Skill signals a reset."""
        if self._context_enabled() and hasattr(self.context, "reset"):
            self.context.reset()
        if self._memory_enabled():
            self.memory.store("current_requirement", None)
            self.memory.store("current_itinerary", None)
            self.memory.store("history", [])
            self.memory.store("reset_flag", True)

    @staticmethod
    def _build_rag_context(rag_results: list[dict]) -> str:
        """将 RAG 检索结果拼接为 LLM 上下文字符串。"""
        if not rag_results:
            return ""
        parts = ["以下是检索到的相关旅游信息：", "---"]
        for i, item in enumerate(rag_results, 1):
            source = item.get("source", "未知来源")
            page = item.get("page", 0)
            content = item.get("content", "").strip()
            parts.append(f"[{i}] 来源：{source} 第{page}页")
            parts.append(content)
            parts.append("")
        parts.append("---")
        return "\n".join(parts)

    def _rag_synthesize(self, user_input: str, rag_results: list[dict], fallback: str) -> str:
        """使用检索到的上下文让 LLM 生成最终回答。

        若检索结果为空，返回 fallback。
        """
        if not rag_results:
            return fallback
        context = self._build_rag_context(rag_results)
        prompt = (
            f"{context}\n\n"
            f"请根据以上信息回答用户问题。如果以上信息不足以回答问题，"
            f"请直接说明。\n用户：{user_input}"
        )
        response = self.model.complete(prompt)
        if self._is_model_error_response(response):
            return fallback
        return response

    def process_turn(self, user_input: str) -> str:
        """Run a single turn.

        Flow:
        1. Update context (optional).
        2. Build prompt with optional memory.
        3. Call Model.complete() to get raw LLM text.
        4. If the model reports an error (missing key, timeout, etc.),
           return the error directly.
        5. Otherwise, call Skill.decide() to route: direct answer or tool call.
        6. If tool call, execute via Tool.
        7. Store to memory (optional).
        """
        logger.info("[Agent] 开始处理用户输入: %s", user_input)

        if self._context_enabled():
            self.context.update(user_input)
            self._maybe_summarize_context()

        prompt = self._build_prompt(user_input)
        logger.debug("[Agent] 构建 Prompt:\n%s", prompt)

        logger.info("[Agent] 调用 LLM (%s:%s)", self.model.provider_name, self.model.model_name)
        llm_response = self.model.complete(prompt)
        logger.debug("[Agent] LLM 原始回复: %s", llm_response[:200])

        # If the model layer reported an error, surface it immediately
        # instead of pretending the agent can still work normally.
        if self._is_model_error_response(llm_response):
            logger.warning("[Agent] LLM 返回错误: %s", llm_response)
            return llm_response

        decision = self.skill.decide(
            user_input, llm_response, self.context, self.memory
        )
        logger.info(
            "[Agent] Skill 决策 -> action=%s, tool=%s",
            decision.get("action"),
            decision.get("tool"),
        )

        if decision.get("reset_context"):
            logger.info("[Agent] 重置上下文")
            self._reset_state()
            return str(decision.get("response", llm_response))

        if decision.get("action") == "tool":
            tool_name = decision.get("tool")
            params = decision.get("params", {})
            logger.info("[Agent] 调用 Tool -> %s, params=%s", tool_name, params)
            raw_result = self.tool.execute(tool_name, params)
            logger.debug("[Agent] Tool 原始返回: %s", str(raw_result)[:300])
            self._maybe_set_itinerary(tool_name, raw_result)

            # RAG 检索需要二次调用 LLM 合成答案
            if tool_name == "rag_retrieve":
                logger.info("[Agent] RAG 检索完成，结果数=%d，开始二次合成", len(raw_result))
                result = self._rag_synthesize(user_input, raw_result, llm_response)
                logger.info("[Agent] RAG 合成完成")
            else:
                result = self._format_tool_result(raw_result)
                logger.info("[Agent] Tool 结果格式化完成")
        else:
            result = decision.get("response", llm_response)
            logger.info("[Agent] 直接回复 (Skill decision=direct)")

        if self._context_enabled() and hasattr(self.context, "add_turn"):
            self.context.add_turn("assistant", result)

        if self._memory_enabled():
            self._remember(user_input, result)

        logger.info("[Agent] 本轮处理完成")
        return str(result)
