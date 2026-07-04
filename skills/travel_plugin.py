"""旅游行程规划 Skill 插件。

把原有的旅游路由逻辑（skills/skill.py 的 Skill 类）包装成 SkillPlugin，
保留完整的多轮槽位合并、3 个子技能调度、跨轮行程恢复等逻辑。
作为通用 Agent 的内置默认插件。
"""

from .base import SkillPlugin, ToolExecutor
from .common import utils, formatter
from .common.models import UserRequirement
from .requirement_alignment.scripts import handle as alignment_handle
from .itinerary_planning.scripts import handle as planning_handle
from .itinerary_validation.scripts import handle as validation_handle


class TravelSkill(SkillPlugin):
    """旅游行程规划插件。

    沿用原 Skill.decide() 的 8 步路由逻辑，
    适配到 SkillPlugin.handle() 接口。
    """

    name = "travel"
    description = "旅游行程规划：根据目的地/天数/预算生成完整行程，支持多轮对话、行程校验与重新规划"
    keywords = [
        "旅游", "旅行", "行程", "玩", "去", "景点", "酒店", "餐厅",
        "天气", "预算", "几天", "天", "成都", "北京", "上海", "三亚",
        "校验", "检查", "验证", "重新", "重做",
    ]
    tools = [
        {
            "name": "search_poi",
            "description": "搜索景点/兴趣点",
            "params": {"city": "城市名", "poi_type": "POI类型如景点", "limit": "返回数量"},
        },
        {
            "name": "get_weather",
            "description": "获取天气预报",
            "params": {"city": "城市名", "days": "天数"},
        },
        {
            "name": "geocode",
            "description": "地址与经纬度互转",
            "params": {"address": "地址", "location": "经度,纬度"},
        },
        {
            "name": "calculate_route",
            "description": "路径规划（驾车/步行/公交）",
            "params": {"origin": "起点坐标", "destination": "终点坐标", "mode": "出行方式"},
        },
        {
            "name": "search_hotel",
            "description": "搜索酒店",
            "params": {"city": "城市名", "price_max": "最高每晚价格"},
        },
        {
            "name": "search_restaurant",
            "description": "搜索餐厅",
            "params": {"city": "城市名", "cuisine": "菜系"},
        },
        {
            "name": "generate_itinerary",
            "description": "生成完整行程方案（含景点/天气/住宿/餐饮/预算）",
            "params": {"destination": "目的地", "days": "天数", "budget_level": "low/mid/high", "preferences": "偏好"},
        },
    ]

    def handle(
        self,
        user_input: str,
        llm_response: str,
        context: dict,
        memory,
        tool_executor: ToolExecutor | None = None,
    ) -> dict:
        """沿用原 Skill.decide 的 8 步路由逻辑。"""
        # 1. 从 memory 恢复已有行程
        utils.restore_itinerary_from_memory(memory)

        # 2. 检测重置意图
        if utils.detect_intent(user_input, utils.RESET_KEYWORDS):
            memory.store("current_requirement", None)
            memory.store("current_itinerary", None)
            memory.store("reset_flag", True)
            return {"action": "direct", "response": "好的，已清空之前的规划。请告诉我您想去哪里？"}

        # 3. 提取并合并槽位
        current_req = utils.get_merged_requirement(user_input, memory)

        # 4. 检测校验意图（已有行程时）
        has_itinerary = memory.retrieve("current_itinerary") is not None
        if has_itinerary and utils.detect_intent(user_input, utils.VALIDATION_KEYWORDS):
            return validation_handle.handle(memory)

        # 5. 检测重新生成意图（已有行程时）
        if has_itinerary and utils.detect_intent(user_input, utils.REGENERATE_KEYWORDS):
            if current_req.is_complete():
                memory.store("current_itinerary", None)
                return planning_handle.handle(current_req)
            return alignment_handle.handle(current_req)

        # 6. 已有行程时的处理
        if has_itinerary:
            from .common import slot_extractor
            new_req = slot_extractor.extract(user_input)
            if new_req.destination or new_req.days or new_req.budget:
                if current_req.is_complete():
                    memory.store("current_itinerary", None)
                    return planning_handle.handle(current_req)
                return alignment_handle.handle(current_req)
            itinerary = memory.retrieve("current_itinerary")
            return {"action": "direct", "response": formatter.format_itinerary(itinerary)}

        # 7. 无行程 → 判断槽位是否齐全
        if not current_req.is_complete():
            return alignment_handle.handle(current_req)

        # 8. 槽位齐全 → 触发行程生成
        return planning_handle.handle(current_req)
