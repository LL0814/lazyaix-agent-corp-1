"""itinerary-planning skill 的处理逻辑。

行程规划：槽位齐全时构建 generate_itinerary 工具调用决策。
"""

from skills.common.models import UserRequirement


def handle(req: UserRequirement) -> dict:
    """处理行程规划决策。

    Args:
        req: 已合并多轮槽位的需求对象（已完整）

    Returns:
        {"action": "tool", "tool": "generate_itinerary", "params": {...}}
    """
    return {
        "action": "tool",
        "tool": "generate_itinerary",
        "params": {
            "destination": req.destination,
            "days": req.days,
            "budget_level": req.budget_level,
            "preferences": req.preferences or "",
        },
    }
