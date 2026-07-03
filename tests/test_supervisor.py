import pytest

from agent import Agent


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
