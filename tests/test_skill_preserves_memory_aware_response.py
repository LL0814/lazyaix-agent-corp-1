from skills import Skill


class RoutingModel:
    def complete_with_tools(self, prompt, tools=None, system=None):
        return '{"action": "direct", "response": "我没有访问长期记忆的能力。"}'


def test_direct_skill_decision_preserves_memory_aware_llm_response():
    skill = Skill(model=RoutingModel())

    decision = skill.decide(
        "请总结我的长期记忆",
        "根据长期记忆：用户喜欢安静酒店，项目使用 Qdrant 和 Ollama bge-m3。",
        {},
        None,
    )

    assert decision == {
        "action": "direct",
        "response": "根据长期记忆：用户喜欢安静酒店，项目使用 Qdrant 和 Ollama bge-m3。",
    }
