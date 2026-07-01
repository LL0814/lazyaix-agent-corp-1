"""Skill 路由主类：单步决策路由。

对外只暴露 Skill 类，实现 decide() 方法。
符合项目 agent.py 的接口约定：
    Skill.decide(user_input, llm_response, context, memory) -> dict

本文件是路由器，3 种决策模式的实际逻辑分别在各自的 skill 文件夹中：
  - skills/requirement-alignment/scripts/handle.py
  - skills/itinerary-planning/scripts/handle.py
  - skills/itinerary-validation/scripts/handle.py
"""

from skills.common import utils, slot_extractor
from skills.common.models import UserRequirement
from skills.requirement_alignment.scripts import handle as alignment_handle
from skills.itinerary_planning.scripts import handle as planning_handle
from skills.itinerary_validation.scripts import handle as validation_handle
from skills.common import formatter


class Skill:
    """Skill 决策层主类。

    被 Agent.process_turn 调用：
        decision = self.skill.decide(user_input, llm_response, context, memory)
    返回决策字典，由 agent.py 执行。
    """

    def decide(self, user_input: str, llm_response: str,
               context: dict, memory) -> dict:
        """单步决策入口（路由器）。

        Args:
            user_input: 用户本轮输入
            llm_response: Model.complete() 的原始响应（练手阶段未使用）
            context: 当前上下文 dict
            memory: Memory 实例，有 store/retrieve 方法

        Returns:
            {"action": "direct", "response": str}
            或
            {"action": "tool", "tool": "generate_itinerary", "params": {...}}
        """
        # 1. 从 memory 恢复已有行程（跨轮持久化）
        utils.restore_itinerary_from_memory(memory)

        # 2. 检测重置意图
        if utils.detect_intent(user_input, utils.RESET_KEYWORDS):
            memory.store("current_requirement", None)
            memory.store("current_itinerary", None)
            memory.store("reset_flag", True)  # 阻止 restore 从 history 恢复旧行程
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
                memory.store("current_itinerary", None)  # 清除旧行程
                return planning_handle.handle(current_req)
            # 信息不全，走追问
            return alignment_handle.handle(current_req)

        # 6. 已有行程时的处理
        if has_itinerary:
            # 6.1 用户本轮提供了新的目的地/天数/预算 → 视为重新规划
            #     （避免"问了北京再问成都"还返回北京旧行程）
            new_req = slot_extractor.extract(user_input)
            if new_req.destination or new_req.days or new_req.budget:
                if current_req.is_complete():
                    memory.store("current_itinerary", None)  # 清除旧行程
                    return planning_handle.handle(current_req)
                # 新信息不全，走追问
                return alignment_handle.handle(current_req)

            # 6.2 无新需求 → 展示已有行程
            itinerary = memory.retrieve("current_itinerary")
            return {"action": "direct", "response": formatter.format_itinerary(itinerary)}

        # 7. 无行程 → 判断槽位是否齐全
        if not current_req.is_complete():
            return alignment_handle.handle(current_req)

        # 8. 槽位齐全 → 触发行程生成
        return planning_handle.handle(current_req)
