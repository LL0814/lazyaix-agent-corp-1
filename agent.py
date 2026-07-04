"""Agent assembly for the team exercise.

This module dynamically assembles an agent from the student modules
(Config, Model, Tool, Skill, Context, Memory, Subagents).  Context and
Memory are injected by loop.py.  If a module is not yet implemented, an
inline stub class is used so the agent can still be instantiated and
exercised.

The Agent acts as a Supervisor: it first calls an LLM to plan whether to
answer directly or delegate tasks to one or more Subagents, then executes
the delegated tasks through the `task` tool, and finally calls the LLM
again to synthesize a final response for the user.
"""

import asyncio
import json
import os
import re
import uuid
from collections.abc import Iterator

from events.bus import EventBus
from events.in_memory import InMemoryEventBus
from events.schema import Event, EventType
from scheduler import Scheduler
from subagents.handlers import ResearcherHandler, WriterHandler
from workflow.coordinator import WorkflowCoordinator
from workflow.graph import TaskGraph, TaskGraphError
from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus

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

        def __init__(self, model=None):
            self.model = model

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

        def __init__(self, model=None):
            self.model = model

        def dispatch(self, agent_name, task_description):
            """Dispatch a task to a sub-agent and return a placeholder result."""
            return f"[STUB] Subagent handled task: {task_description}"


try:
    from girlfriend import GirlfriendEngine
except ImportError:
    GirlfriendEngine = None


class Agent:
    """Dynamically assembled agent with Supervisor planning capabilities.

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
        # Tool 接收 model 以驱动 Subagent 分发（task action）。
        self.tool = Tool(self.model)
        self.subagent = Subagent(self.model)
        # Girlfriend 人格层（可选）：ENABLE_GIRLFRIEND_MODE=true 时启用。
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

    def _event_driven_enabled(self):
        return self.config.get("ENABLE_EVENT_DRIVEN", "false").lower() == "true"

    def _streaming_enabled(self):
        return self.config.get("ENABLE_STREAMING", "true").lower() == "true"

    def _vector_memory_enabled(self):
        return self.config.get("ENABLE_VECTOR_MEMORY", "true").lower() == "true"

    def _girlfriend_enabled(self):
        return self.config.get("ENABLE_GIRLFRIEND_MODE", "true").lower() == "true"

    def _build_tasks_from_plan(self, tasks_data: list[dict]) -> dict[str, Task]:
        """Convert LLM task plan into Task objects."""
        tasks: dict[str, Task] = {}
        for item in tasks_data:
            if not isinstance(item, dict):
                raise TaskGraphError(f"Task entry must be an object, got {type(item).__name__}")
            task_id = item.get("task_id")
            target_capability = item.get("target_capability")
            if not task_id or not target_capability:
                raise TaskGraphError(
                    f"Each task must have task_id and target_capability: {item}"
                )
            if task_id in tasks:
                raise TaskGraphError(f"Duplicate task_id in plan: {task_id}")
            if "instructions" not in item:
                raise TaskGraphError(f"Task missing required field 'instructions': {item}")
            task = Task(
                task_id=task_id,
                task_type=item.get("task_type", "generic"),
                target_capability=target_capability,
                instructions=item["instructions"],
                input=item.get("input"),
                dependencies=item.get("dependencies", []),
                input_refs=item.get("input_refs", []),
                required_for_completion=item.get("required_for_completion", True),
            )
            tasks[task.task_id] = task
        return tasks

    def _build_planning_prompt_v2(self, user_input: str) -> str:
        return (
            "You are a supervisor agent. You can delegate tasks to two capabilities:\n"
            "- researcher: good at research, analysis, and summarization\n"
            "- writer: good at writing, copywriting, and content generation\n\n"
            "Based on the user's request, decide whether to answer directly or "
            "delegate to one or more tasks. Follow these rules:\n"
            "- If the user asks for creative writing, an essay, a poem, a story, "
            "  or copywriting that does NOT require external facts or research, "
            "  use ONLY the writer capability.\n"
            "- If the user asks for facts, research, analysis, or a summary of "
            "  information without asking for a written document, use ONLY the "
            "  researcher capability.\n"
            "- If the user asks for a report or document that requires research, "
            "  first use researcher to gather facts, then use writer to produce "
            "  the final document. The writer task should depend on the researcher "
            "  task.\n"
            "- If the request is simple, answer directly.\n"
            "- Tasks may run in parallel if they have no dependencies.\n\n"
            "Respond with a JSON object in one of these forms:\n"
            '{"action": "direct", "response": "your direct answer"}\n'
            'or\n'
            '{"action": "delegate", "tasks": [{"task_id": "research_001", "task_type": "research", "target_capability": "researcher", "instructions": "...", "dependencies": [], "input_refs": [], "required_for_completion": true}, ...]}\n\n'
            f"User request: {user_input}\n"
            "Decision:"
        )

    def _build_prompt(self, user_input, vector_memories=None):
        """Build the prompt sent to the model.

        融合 supervisor 规划 + memory 上下文 + 长期记忆 + 向量检索 + girlfriend 人格。
        """
        parts = []

        # 长期结构化偏好记忆（memory.json 中的非 history 键）
        if self._memory_enabled():
            all_keys = getattr(self.memory, "list", lambda: [])()
            for key in all_keys:
                if key == "history":
                    continue
                value = self.memory.retrieve(key)
                if value is not None:
                    parts.append(f"- {key}: {value}")

        # 向量记忆检索结果
        vector_items = self._format_vector_memories(vector_memories or [])
        if vector_items:
            parts.append("相关历史对话检索结果：")
            parts.extend(vector_items)

        # 短期对话历史（memory.history）
        if self._memory_enabled():
            history = self.memory.retrieve("history") or []
            memory_text = "\n".join(
                f"Q: {h['input']}\nA: {h['response']}" for h in history[-3:]
            )
            if memory_text:
                parts.append(memory_text)

        # 上下文压缩历史
        if self._context_enabled():
            messages = self.context.get_messages()
            if messages:
                context_text = "\n".join(
                    f"{m.get('role', 'user')}: {m.get('content', '')}"
                    for m in messages
                )
                parts.append(f"Conversation history:\n{context_text}")

        parts.append(f"Q: {user_input}")
        base_prompt = "\n\n".join(parts)
        return self._apply_girlfriend_prompt(user_input, base_prompt)

    def _apply_girlfriend_prompt(self, user_input, base_prompt):
        """若启用 girlfriend 人格层，则对 prompt 做二次包装。"""
        if self.girlfriend is None:
            return base_prompt
        return self.girlfriend.build_prompt(user_input, base_prompt)

    def _format_vector_memories(self, vector_memories):
        """格式化向量检索返回的记忆片段。"""
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

    async def _process_turn_event_driven(self, user_input: str) -> str:
        """Run the turn using event-driven task scheduling."""
        event_bus = InMemoryEventBus()
        max_retries = int(self.config.get("MAX_RETRIES", "2"))
        coordinator = WorkflowCoordinator(event_bus, max_retries=max_retries)
        scheduler = Scheduler(
            event_bus,
            {
                "researcher": ResearcherHandler(self.model, event_bus),
                "writer": WriterHandler(self.model, event_bus),
            },
        )

        event_bus.subscribe(EventType.TASK_READY, scheduler.handle_task_ready)
        event_bus.subscribe(EventType.AGENT_COMPLETED, coordinator.handle_task_completed)
        event_bus.subscribe(EventType.AGENT_FAILED, coordinator.handle_task_failed)
        await event_bus.start()

        try:
            prompt = self._build_planning_prompt_v2(user_input)
            raw = self.model.complete(prompt)
            decision = self._parse_plan_v2(raw)

            if decision.get("action") == "direct":
                return decision.get("response", "")

            try:
                workflow = Workflow(
                    workflow_id=str(uuid.uuid4()),
                    trace_id=str(uuid.uuid4()),
                    user_input=user_input,
                    tasks=self._build_tasks_from_plan(decision.get("tasks", [])),
                )

                future = asyncio.get_running_loop().create_future()
                coordinator.set_completion_future(workflow.workflow_id, future)
                await coordinator.start_workflow(workflow)
            except TaskGraphError as exc:
                return f"[Workflow planning error] {exc}"

            timeout_seconds = float(
                self.config.get("WORKFLOW_TIMEOUT_SECONDS", "300")
            )
            try:
                await asyncio.wait_for(future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return f"[Workflow timeout] did not complete within {timeout_seconds}s"

            return self._finalize_workflow(workflow, user_input)
        finally:
            await event_bus.stop()

    def _parse_plan_v2(self, raw: str) -> dict:
        """Parse LLM output; on failure fall back to direct response."""
        raw = raw.strip()
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return {"action": "direct", "response": raw}
            try:
                decision = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {"action": "direct", "response": raw}

        action = decision.get("action")
        if action == "direct" and "response" in decision:
            return decision
        if action == "delegate":
            tasks = decision.get("tasks", [])
            if isinstance(tasks, list):
                return decision
        return {"action": "direct", "response": raw}

    def _finalize_workflow(self, workflow: Workflow, user_input: str) -> str:
        """Produce final response from completed workflow."""
        if workflow.status == WorkflowStatus.FAILED:
            return f"[Workflow failed] {workflow.error or 'unknown error'}"

        completed = [
            t for t in workflow.tasks.values() if t.status == TaskStatus.COMPLETED
        ]
        if not completed:
            return "[No tasks completed]"

        # 如果只有一个必需的已完成任务，直接返回其结果。
        required_completed = [t for t in completed if t.required_for_completion]
        if len(required_completed) == 1:
            return str(required_completed[0].result)

        # 否则进行汇总。
        results = [
            {"agent": t.target_capability, "result": t.result} for t in completed
        ]
        return self._summarize(user_input, results, self.context.get(), self.memory)

    def _parse_plan(self, raw: str):
        """Parse the Supervisor planning JSON from raw LLM output.

        Supports:
        - {"action": "direct", "response": "..."}
        - {"action": "delegate", "tasks": [{"agent": "...", "description": "..."}, ...]}
        - Backward compatibility: {"action": "delegate", "agent": "...", "description": "..."}
        Returns None if parsing fails or required fields are missing.
        """
        raw = raw.strip()
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return None
            try:
                decision = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        # Backward compatibility: single-agent format -> tasks array
        if (
            decision.get("action") == "delegate"
            and "agent" in decision
            and "tasks" not in decision
        ):
            decision["tasks"] = [
                {
                    "agent": decision["agent"],
                    "description": decision.get("description", ""),
                }
            ]

        # Reject example/placeholder output copied from the prompt (common with
        # stub LLMs that echo the prompt).
        if self._is_example_output(decision):
            return None

        action = decision.get("action")
        if action == "direct" and "response" in decision:
            return decision
        if action == "delegate":
            tasks = decision.get("tasks", [])
            if isinstance(tasks, list) and all(
                isinstance(t, dict) and "agent" in t and "description" in t
                for t in tasks
            ):
                return decision
        return None

    def _is_example_output(self, decision: dict) -> bool:
        """Return True if the parsed decision looks like the prompt examples."""
        if decision.get("action") == "direct":
            response = decision.get("response", "")
            if "your direct answer" in response or "EXAMPLE" in response:
                return True
        if decision.get("action") == "delegate":
            for task in decision.get("tasks", []):
                desc = task.get("description", "")
                if "task description" in desc or "EXAMPLE" in desc:
                    return True
        return False

    def _plan(self, user_input, context, memory):
        """Use the LLM to decide whether to answer directly or delegate.

        Returns a decision dict. On parse failure, falls back to the Skill
        module for rule-based routing.
        """
        prompt = (
            "You are a supervisor agent. You have two subagents:\n"
            "- researcher: good at research, analysis, and summarization\n"
            "- writer: good at writing, copywriting, and content generation\n\n"
            "Based on the user's request, decide whether to answer directly or "
            "delegate to one or more subagents. You may delegate to a single "
            "subagent or both if the task benefits from both research and writing.\n\n"
            "Respond with a JSON object in one of these two forms:\n"
            '{"action": "direct", "response": "your direct answer to the user"}\n'
            'or\n'
            '{"action": "delegate", "tasks": [{"agent": "researcher|writer", "description": "task description"}, ...]}\n\n'
            f"User request: {user_input}\n"
            "Decision:"
        )
        raw = self.model.complete(prompt)
        decision = self._parse_plan(raw)
        if decision is None:
            # Fallback to rule-based skill routing.
            skill_decision = self.skill.decide(user_input, raw, context, memory)
            if (
                skill_decision.get("action") == "tool"
                and skill_decision.get("tool") == "task"
            ):
                return {
                    "action": "delegate",
                    "tasks": [
                        {
                            "agent": skill_decision["params"]["agent"],
                            "description": skill_decision["params"]["description"],
                        }
                    ],
                }
            return {"action": "direct", "response": raw}
        return decision

    def _summarize(self, user_input, results, context, memory):
        """Use the LLM to synthesize subagent results into a final response."""
        prompt = (
            "You are a supervisor agent. You delegated tasks to one or more "
            "subagents and received the following results.\n\n"
            f"User request: {user_input}\n\n"
            "Subagent results:\n"
        )
        for item in results:
            prompt += f"- [{item['agent']}] {item['result']}\n"
        prompt += (
            "\nPlease synthesize these results into a final, natural, and "
            "helpful response for the user. Start your response by briefly "
            "mentioning which subagents you used, for example: "
            "'I used the researcher and writer subagents to help with this.' "
            "Then provide the synthesized answer."
        )
        return self.model.complete(prompt)

    def process_turn(self, user_input: str) -> str:
        """Run a single turn.

        Flow:
        1. Update context (optional).
        2. Plan: LLM 决定 direct / delegate（事件驱动或同步两条路径）。
        3. 若 delegate，通过 Tool.task 分发到 Subagent worker。
        4. 汇总结果并存储到 memory（optional）。
        """
        if self._context_enabled():
            self.context.update(user_input)

        if self._event_driven_enabled():
            result = asyncio.run(self._process_turn_event_driven(user_input))
        else:
            result = self._process_turn_sync(user_input)

        self._after_turn(user_input, result)

        return str(result)

    def _process_turn_sync(self, user_input: str) -> str:
        """Original synchronous implementation (preserved)."""
        plan = self._plan(user_input, self.context.get(), self.memory)

        if plan.get("action") == "delegate":
            results = []
            for task in plan.get("tasks", []):
                agent_result = self.tool.execute(
                    "task",
                    {"agent": task["agent"], "description": task["description"]},
                )
                results.append({"agent": task["agent"], "result": agent_result})
            used_agents = ", ".join(r["agent"] for r in results)
            prefix = f"[使用了子agent: {used_agents}]\n\n"
            summary = self._summarize(
                user_input, results, self.context.get(), self.memory
            )
            result = prefix + summary
        else:
            result = plan.get("response", "")

        return str(result)

    def process_turn_stream(self, user_input: str) -> Iterator[str]:
        """Run a single turn and stream direct model output.

        流式仅对 direct 模式生效；delegate 走同步 _process_turn_sync。
        """
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
