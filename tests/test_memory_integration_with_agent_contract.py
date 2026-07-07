from pathlib import Path

from agent import Agent
from context import Context
from memory import Memory
from memory.embeddings import FakeEmbeddingProvider
from memory.models import MemoryClassification, MemoryKind


class FakeIndex:
    def __init__(self):
        self.points = {}

    def upsert_memory(self, record, vector):
        self.points[record.memory_id] = {"record": record, "vector": vector}

    def search(self, vector, filters, top_k):
        results = []
        for memory_id, item in self.points.items():
            record = item["record"]
            if record.tenant_id != filters.get("tenant_id"):
                continue
            if record.user_id != filters.get("user_id"):
                continue
            if record.project_id != filters.get("project_id"):
                continue
            if record.status.value != filters.get("status"):
                continue
            results.append({"memory_id": memory_id, "score": 0.9})
        return results[:top_k]

    def delete_memory(self, memory_id):
        self.points.pop(memory_id, None)


class StaticExtractor:
    def extract(self, text: str) -> MemoryClassification:
        return MemoryClassification(
            should_remember=True,
            kind=MemoryKind.SEMANTIC,
            content="用户偏好入住安静的酒店。",
            confidence=0.9,
            importance=0.8,
            reason="测试抽取稳定偏好",
        )


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


def test_agent_auto_processes_outbox_and_injects_long_term_memory(tmp_path: Path):
    context = Context()
    memory = Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
        candidate_extractor=StaticExtractor(),
    )
    agent = Agent(context=context, memory=memory)
    prompts = []

    def complete(prompt, system=None):
        prompts.append(prompt)
        return "测试回复"

    agent.model.complete = complete
    agent.skill.decide = lambda user_input, llm_response, context, memory: {
        "action": "direct",
        "response": llm_response,
    }

    agent.process_turn("我喜欢住安静一点的酒店")
    agent.process_turn("我住宿有什么偏好？")

    assert memory.debug_counts().records >= 1
    assert "Long-term memories:" in prompts[-1]
    assert "用户偏好入住安静的酒店。" in prompts[-1]


def test_agent_prompt_injects_summary_memory(tmp_path: Path):
    context = Context()
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})
    memory.update_summary("用户正在验证 Ollama bge-m3 的企业级记忆系统。")
    agent = Agent(context=context, memory=memory)

    prompt = agent._build_prompt("我们现在在验证什么？")

    assert "Memory summary:" in prompt
    assert "用户正在验证 Ollama bge-m3 的企业级记忆系统。" in prompt
