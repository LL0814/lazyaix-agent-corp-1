import pytest
from agent import Agent


class _StubContext:
    def update(self, user_input):
        pass

    def get(self):
        return {}


class _StubMemory:
    def retrieve(self, key):
        return None

    def store(self, key, value):
        pass


def make_agent():
    return Agent(_StubContext(), _StubMemory())


def test_default_state_store_is_memory():
    agent = make_agent()
    assert agent._state_store_backend() == "memory"
