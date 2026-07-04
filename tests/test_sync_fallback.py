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
    def complete(self, prompt: str) -> str:
        # Return the delegate plan for the supervisor planning prompt; for
        # downstream prompts (subagent tasks, summarize) return a deterministic
        # response containing the writer marker so the assertion is meaningful.
        if (
            "You are a supervisor agent" in prompt
            and "You have two subagents:" in prompt
        ):
            return '{"action": "delegate", "tasks": [{"agent": "writer", "description": "write poem"}]}'
        return "[StubModel] Synthesized [Writer] result"


def test_sync_path_still_works(monkeypatch):
    monkeypatch.setenv("ENABLE_EVENT_DRIVEN", "false")
    agent = Agent(StubContext(), StubMemory())
    agent.model = StubModel()
    response = agent.process_turn("write a poem")
    assert "[Writer]" in response
    assert "[使用了子agent:" in response
