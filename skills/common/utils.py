"""Skills 共享辅助函数。

包括：
  - 意图关键词常量
  - detect_intent: 关键词意图检测
  - get_merged_requirement: 多轮槽位合并
  - restore_itinerary_from_memory: 从 history 恢复行程
"""

import logging
from .models import UserRequirement
from . import slot_extractor

logger = logging.getLogger(__name__)

# ============ 意图关键词 ============

VALIDATION_KEYWORDS = ["校验", "检查", "验证", "有问题吗", "可行吗", "看看行程"]
REGENERATE_KEYWORDS = ["重新", "再生成", "换一个", "重做"]
RESET_KEYWORDS = ["重新开始", "换个目的地", "不去了", "取消"]

# 旅行意图关键词。命中任一关键词即进入旅行 Skill 流程。
TRAVEL_KEYWORDS = [
    "旅游", "旅行", "出行", "游玩", "行程", "攻略",
    "景点", "景区", "酒店", "住宿", "民宿", "机票", "车票", "高铁",
    "路线", "自驾", "跟团", "自由行", "亲子游", "蜜月", "度假",
    "目的地", "预算", "门票", "导游", "包车", "租车",
]


# ============ 意图检测 ============

def detect_intent(text: str, keywords: list[str]) -> bool:
    """检测用户输入是否包含指定关键词。"""
    return any(kw in text for kw in keywords)


# ============ 槽位合并 ============

def get_merged_requirement(user_input: str, context=None, memory=None) -> UserRequirement:
    """提取并合并槽位。

    用户可能分多轮提供信息，每轮提取后与 context（优先）或 memory 中已存的槽位合并。
    本轮非空的字段覆盖已有字段。合并后的槽位会同时写回 context 和 memory（如有）。
    """
    new_req = slot_extractor.extract(user_input)

    prev_req_dict = {}
    if context is not None and hasattr(context, "get_slots"):
        prev_req_dict = context.get_slots()
    elif memory is not None:
        prev_req_dict = memory.retrieve("current_requirement") or {}

    # 用户重新提供信息时，清除 reset 标记
    if new_req.destination or new_req.days or new_req.budget:
        if memory is not None:
            memory.store("reset_flag", False)

    merged = UserRequirement(
        destination=new_req.destination or prev_req_dict.get("destination"),
        days=new_req.days or prev_req_dict.get("days"),
        budget=new_req.budget or prev_req_dict.get("budget"),
        budget_level=new_req.budget_level if new_req.budget else prev_req_dict.get("budget_level", "mid"),
        preferences=new_req.preferences or prev_req_dict.get("preferences"),
    )

    slots = {
        "destination": merged.destination,
        "days": merged.days,
        "budget": merged.budget,
        "budget_level": merged.budget_level,
        "preferences": merged.preferences,
    }

    if context is not None and hasattr(context, "set_slots"):
        context.set_slots(slots)
    if memory is not None:
        memory.store("current_requirement", slots)

    return merged


# ============ 行程恢复 ============

def restore_itinerary_from_memory(memory) -> None:
    """从 memory 的 history 中恢复已有行程。

    agent.py 执行 Tool 后，把 Itinerary 对象存到 memory["history"]。
    本方法遍历 history 找最近的 Itinerary，缓存到 "current_itinerary"。

    注意：reset 操作会显式 store("current_itinerary", None)，
    本方法检测到 None 时不会覆盖（视为"用户主动清空"）。
    """
    # 显式 None 表示用户已重置，不恢复
    if memory.retrieve("current_itinerary") is not None:
        return
    # 检查是否刚刚 reset（用 flag 标记）
    if memory.retrieve("reset_flag"):
        return

    history = memory.retrieve("history") or []
    for turn in reversed(history):
        response = turn.get("response")
        if hasattr(response, "days") and hasattr(response, "destination"):
            memory.store("current_itinerary", response)
            logger.debug("从 history 恢复行程: %s", response.destination)
            return
