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

import json
import os
import re

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
        self.skill = Skill()
        self.tool = Tool(self.model)
        self.subagent = Subagent(self.model)

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

        Memory is included only when ENABLE_MEMORY is true.
        """
        if not self._memory_enabled():
            return user_input
        history = self.memory.retrieve("history") or []
        memory_text = "\n".join(
            f"Q: {h['input']}\nA: {h['response']}" for h in history[-3:]
        )
        if memory_text:
            return f"{memory_text}\nQ: {user_input}"
        return user_input

    def _remember(self, user_input, response):
        """Store the turn in memory when ENABLE_MEMORY is true."""
        history = self.memory.retrieve("history") or []
        history.append({"input": user_input, "response": response})
        self.memory.store("history", history[-10:])

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
        """Run a single turn through the Supervisor pipeline.

        Flow:
        1. Update context (optional).
        2. Call _plan() to decide direct answer or delegation.
        3. If delegation, execute each task via the `task` tool and collect results.
        4. Call _summarize() to produce the final user-facing response.
        5. Store to memory (optional).
        """
        if self._context_enabled():
            self.context.update(user_input)

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

        if self._memory_enabled():
            self._remember(user_input, result)

        return str(result)
