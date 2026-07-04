"""requirement-alignment skill 的处理逻辑。

需求对齐：槽位缺失时生成追问文案。
"""

from skills.common.models import UserRequirement


def handle(req: UserRequirement) -> dict:
    """处理需求对齐决策。

    Args:
        req: 已合并多轮槽位的需求对象（存在缺失项）

    Returns:
        {"action": "direct", "response": 追问文案}
    """
    missing = req.missing_slots()
    prompts = {
        "destination": "您想去哪里旅游呢？比如成都、北京、云南等。",
        "days": "您计划玩几天呢？",
        "budget": "您的预算大概是多少？比如 3000 元、穷游、舒适等。",
    }
    followup = " ".join(prompts[slot] for slot in missing if slot in prompts)

    # 附带已识别的信息，让用户知道系统理解了什么
    confirmed = []
    if req.destination:
        confirmed.append(f"目的地：{req.destination}")
    if req.days:
        confirmed.append(f"天数：{req.days} 天")
    if req.budget:
        confirmed.append(f"预算：{req.budget} 元")
    if req.preferences:
        confirmed.append(f"偏好：{req.preferences}")

    response = followup
    if confirmed:
        response = "已了解：" + "，".join(confirmed) + "\n" + response

    return {"action": "direct", "response": response}
