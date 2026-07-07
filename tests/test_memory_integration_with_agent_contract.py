from pathlib import Path

from agent import Agent
from context import Context
from memory import Memory


def test_agent_uses_real_memory_without_code_changes(tmp_path: Path):
    context = Context()
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})
    agent = Agent(context=context, memory=memory)
    agent.model.complete = lambda prompt: "测试回复"
    agent.skill.decide = lambda user_input, llm_response, context, memory: {
        "action": "direct",
        "response": "测试回复",
    }

    response = agent.process_turn("你好")

    assert response == "测试回复"
    assert memory.retrieve("history") == [{"input": "你好", "response": "测试回复"}]


def test_travel_skill_keys_round_trip(tmp_path: Path):
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    memory.store("current_requirement", {"destination": "成都", "days": 3, "budget": 3000})
    memory.store("current_itinerary", None)
    memory.store("reset_flag", True)

    restored = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    assert restored.retrieve("current_requirement") == {
        "destination": "成都",
        "days": 3,
        "budget": 3000,
    }
    assert restored.retrieve("current_itinerary") is None
    assert restored.retrieve("reset_flag") is True
