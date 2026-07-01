"""itinerary-validation skill 的处理逻辑。

行程校验：检查已有行程的时间/交通/预算，输出校验报告。
"""

from skills.common import validator
from skills.common import formatter


def handle(memory) -> dict:
    """处理行程校验决策。

    Args:
        memory: Memory 实例，读取 current_itinerary

    Returns:
        {"action": "direct", "response": 校验报告文本}
    """
    itinerary = memory.retrieve("current_itinerary")
    if not itinerary:
        return {
            "action": "direct",
            "response": "还没有生成行程，无法校验。请先告诉我您的旅行需求。"
        }

    report = validator.validate(itinerary)
    text = formatter.format_validation_report(report)

    # 如果行程有效，附带展示行程
    if report["is_valid"]:
        text += "\n\n" + formatter.format_itinerary(itinerary)

    return {"action": "direct", "response": text}
