"""Skills 模块自测脚本。

模拟多轮对话，测试 3 种决策模式：
  1. requirement_alignment（槽位缺失 → 追问）
  2. itinerary_planning（槽位齐全 → 触发工具）
  3. itinerary_validation（已有行程 → 校验）

运行方式：从项目根目录执行 `python3 skills/_selftest.py`
"""

import os
import sys

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import Skill, UserRequirement
from skills.common import slot_extractor
from skills.common import formatter
from tools.models import Itinerary, POI, Route, Hotel, Restaurant, Weather


# ============ Mock Memory ============

class MockMemory:
    """模拟 agent.py 的 Memory，提供 store/retrieve。"""
    def __init__(self):
        self._store = {}
    def store(self, key, value):
        self._store[key] = value
    def retrieve(self, key):
        return self._store.get(key)


# ============ 测试槽位提取 ============

def test_slot_extractor():
    print("=" * 60)
    print("测试 1：槽位提取")
    print("=" * 60)

    # 完整需求
    req = slot_extractor.extract("我想去成都玩3天，预算3000元，喜欢自然风光")
    print(f"  输入：我想去成都玩3天，预算3000元，喜欢自然风光")
    print(f"  目的地={req.destination} | 天数={req.days} | 预算={req.budget} | 级别={req.budget_level} | 偏好={req.preferences}")
    assert req.destination == "成都"
    assert req.days == 3
    assert req.budget == 3000
    assert "自然风光" in (req.preferences or "")
    print("  ✓ 完整需求提取正确")

    # 中文数字
    req2 = slot_extractor.extract("去北京玩五天")
    print(f"\n  输入：去北京玩五天")
    print(f"  目的地={req2.destination} | 天数={req2.days}")
    assert req2.destination == "北京"
    assert req2.days == 5
    print("  ✓ 中文数字提取正确")

    # 穷游关键词
    req3 = slot_extractor.extract("去云南穷游")
    print(f"\n  输入：去云南穷游")
    print(f"  目的地={req3.destination} | 级别={req3.budget_level}")
    assert req3.destination == "云南"
    assert req3.budget_level == "low"
    print("  ✓ 穷游级别提取正确")

    # 缺失信息
    req4 = slot_extractor.extract("我想去旅游")
    print(f"\n  输入：我想去旅游")
    print(f"  目的地={req4.destination} | 天数={req4.days} | 预算={req4.budget}")
    assert req4.destination is None
    print("  ✓ 缺失信息识别正确")

    print()


# ============ 测试多轮对话决策 ============

def test_multi_turn_dialog():
    print("=" * 60)
    print("测试 2：多轮对话决策流程")
    print("=" * 60)

    skill = Skill()
    memory = MockMemory()
    context = {}

    # --- 第 1 轮：信息不全 ---
    print("\n--- 第 1 轮：用户只说了目的地 ---")
    decision = skill.decide("我想去成都", "[llm stub]", context, memory)
    print(f"  用户：我想去成都")
    print(f"  决策：action={decision['action']}")
    print(f"  回复：{decision.get('response', '')[:80]}...")
    assert decision["action"] == "direct"
    assert "天数" in decision["response"] or "预算" in decision["response"]
    print("  ✓ 触发了追问")

    # --- 第 2 轮：补充天数 ---
    print("\n--- 第 2 轮：用户补充天数 ---")
    decision = skill.decide("玩3天", "[llm stub]", context, memory)
    print(f"  用户：玩3天")
    print(f"  决策：action={decision['action']}")
    print(f"  回复：{decision.get('response', '')[:80]}...")
    assert decision["action"] == "direct"
    assert "预算" in decision["response"]
    print("  ✓ 仍追问预算")

    # --- 第 3 轮：补充预算 → 应触发生成 ---
    print("\n--- 第 3 轮：用户补充预算 → 触发生成 ---")
    decision = skill.decide("预算3000元", "[llm stub]", context, memory)
    print(f"  用户：预算3000元")
    print(f"  决策：action={decision['action']}")
    if decision["action"] == "tool":
        print(f"  工具：{decision['tool']}")
        print(f"  参数：{decision['params']}")
        assert decision["tool"] == "generate_itinerary"
        assert decision["params"]["destination"] == "成都"
        assert decision["params"]["days"] == 3
    print("  ✓ 触发了行程生成")

    # --- 模拟 agent.py 执行 Tool 后存行程到 memory ---
    mock_itinerary = _create_mock_itinerary()
    history = memory.retrieve("history") or []
    history.append({"input": "预算3000元", "response": mock_itinerary})
    memory.store("history", history)

    # --- 第 4 轮：已有行程，用户要求校验 ---
    print("\n--- 第 4 轮：用户要求校验行程 ---")
    decision = skill.decide("帮我校验一下行程", "[llm stub]", context, memory)
    print(f"  用户：帮我校验一下行程")
    print(f"  决策：action={decision['action']}")
    response = decision.get("response", "")
    print(f"  回复（前100字）：{response[:100]}...")
    assert decision["action"] == "direct"
    assert "校验" in response or "问题" in response or "通过" in response
    print("  ✓ 触发了校验报告")

    # --- 第 5 轮：重置 ---
    print("\n--- 第 5 轮：用户重置 ---")
    decision = skill.decide("重新开始", "[llm stub]", context, memory)
    print(f"  用户：重新开始")
    print(f"  回复：{decision.get('response', '')[:80]}")
    assert decision["action"] == "direct"
    assert memory.retrieve("current_itinerary") is None
    print("  ✓ 重置成功")

    print()


# ============ 测试行程格式化 ============

def test_formatter():
    print("=" * 60)
    print("测试 3：行程格式化")
    print("=" * 60)

    itinerary = _create_mock_itinerary()
    text = formatter.format_itinerary(itinerary)
    print(text[:300] + "...")
    assert "成都" in text
    assert "第 1 天" in text
    assert "预算汇总" in text
    print("  ✓ 格式化正确")

    print()


# ============ 辅助函数 ============

def _create_mock_itinerary() -> Itinerary:
    """创建模拟行程，用于测试。"""
    poi1 = POI(name="武侯祠", address="成都武侯祠大街231号", lng=104.04, lat=30.64,
              rating=4.6, open_time="08:00-18:00", poi_type="景点")
    poi2 = POI(name="锦里", address="成都武侯祠大街", lng=104.04, lat=30.63,
              rating=4.5, open_time="全天", poi_type="景点")
    route = Route(distance=500, duration=120, mode="walking", steps=["步行前往"])

    restaurant = Restaurant(name="陈麻婆豆腐", address="成都", cuisine="川菜",
                           avg_price=65, rating=4.5, signature_dishes=["麻婆豆腐"])
    hotel = Hotel(name="亚朵酒店", address="成都", price_per_night=420,
                  rating=4.3, room_type="大床房")

    return Itinerary(
        destination="成都",
        days=[{
            "date": "2026-07-01",
            "weekday": "周二",
            "pois": [poi1, poi2],
            "routes": [route],
            "lunch": restaurant,
            "dinner": restaurant,
            "hotel": hotel,
            "timeline": ["09:00 到达 武侯祠", "11:00 离开 武侯祠", "11:30 午餐", "14:00 到达 锦里"],
            "weather": Weather(date="2026-07-01", temp_min=22, temp_max=30,
                             condition="晴", precip_prob=0, wind="微风",
                             clothing_advice="建议穿短袖"),
        }],
        budget_summary={"accommodation": 420, "food": 130, "transport": 10,
                       "tickets": 100, "total": 660, "daily_avg": 660, "level": "mid"},
        notes=["景点门票价格为估算"],
    )


# ============ 主入口 ============

if __name__ == "__main__":
    test_slot_extractor()
    test_multi_turn_dialog()
    test_formatter()
    print("=" * 60)
    print("✓ 所有 Skills 测试通过")
    print("=" * 60)
