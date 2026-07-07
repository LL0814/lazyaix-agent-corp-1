import pytest

from agent import Agent
from workflow.coordinator import WorkflowCoordinator


class StubMemory:
    def retrieve(self, key):
        return None

    def store(self, key, value):
        pass


class StubContext:
    def update(self, user_input):
        pass

    def get(self):
        return {}


class StubModel:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str) -> str:
        # Return the stored planning response only for the planning prompt.
        # For all other prompts (subagent tasks, summarize), return a
        # deterministic response so multi-task workflows can be asserted.
        if "You are a supervisor agent" in prompt and "delegate tasks to two capabilities" in prompt:
            return self._response
        return "[StubModel] Synthesized [Writer] result"


def make_agent(model_response: str, monkeypatch) -> Agent:
    monkeypatch.setenv("ENABLE_EVENT_DRIVEN", "true")
    agent = Agent(StubContext(), StubMemory())
    agent.model = StubModel(model_response)
    return agent


def test_supervisor_direct_answer(monkeypatch):
    agent = make_agent('{"action": "direct", "response": "hello"}', monkeypatch)
    assert agent.process_turn("hi") == "hello"


def test_supervisor_event_driven_writer_only(monkeypatch):
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "write_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "write poem", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("write a poem")
    assert "[Writer]" in response


def test_supervisor_event_driven_researcher_then_writer(monkeypatch):
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "research_001", "task_type": "research", "target_capability": "researcher", '
        '"instructions": "research AI", "dependencies": [], "input_refs": [], "required_for_completion": true},'
        '{"task_id": "write_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "write report", "dependencies": ["research_001"], "input_refs": ["research_001.result"], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("research and report")
    assert "[Writer]" in response


def test_supervisor_invalid_task_graph_graceful_error(monkeypatch):
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "bad_001", "task_type": "write", '
        '"instructions": "missing capability", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("do something impossible")
    assert response.startswith("[Workflow planning error]")


def test_supervisor_event_driven_timeout(monkeypatch):
    import asyncio as aio

    monkeypatch.setenv("WORKFLOW_TIMEOUT_SECONDS", "0.01")

    async def never_complete(self, event):
        await aio.Event().wait()

    monkeypatch.setattr("subagents.handlers.WriterHandler.__call__", never_complete)

    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "write_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "write poem", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("write a poem")
    assert "[Workflow timeout]" in response
    assert "0.01s" in response


def test_supervisor_custom_max_retries_from_config(monkeypatch):
    monkeypatch.setenv("MAX_RETRIES", "5")
    captured = {}

    original_init = WorkflowCoordinator.__init__

    def spy_init(self, event_bus, state_store, max_retries=2):
        captured["max_retries"] = max_retries
        original_init(self, event_bus, state_store, max_retries)

    monkeypatch.setattr(WorkflowCoordinator, "__init__", spy_init)

    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "write_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "write poem", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    agent.process_turn("write a poem")

    assert captured.get("max_retries") == 5


def test_supervisor_duplicate_task_id_graceful_error(monkeypatch):
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "dup_001", "task_type": "research", "target_capability": "researcher", '
        '"instructions": "first task", "dependencies": [], "input_refs": [], "required_for_completion": true},'
        '{"task_id": "dup_001", "task_type": "write", "target_capability": "writer", '
        '"instructions": "duplicate task", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("duplicate task ids")
    assert response.startswith("[Workflow planning error]")
    assert "Duplicate task_id" in response


def test_supervisor_missing_task_id_graceful_error(monkeypatch):
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_type": "write", "target_capability": "writer", '
        '"instructions": "missing task_id", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("missing task id")
    assert response.startswith("[Workflow planning error]")
    assert "task_id" in response


def test_supervisor_missing_target_capability_graceful_error(monkeypatch):
    plan = (
        '{"action": "delegate", "tasks": ['
        '{"task_id": "bad_001", "task_type": "write", '
        '"instructions": "missing capability", "dependencies": [], "input_refs": [], "required_for_completion": true}'
        ']}'
    )
    agent = make_agent(plan, monkeypatch)
    response = agent.process_turn("missing target capability")
    assert response.startswith("[Workflow planning error]")
    assert "target_capability" in response
