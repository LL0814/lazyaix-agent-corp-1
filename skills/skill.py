"""Skill 路由主类：单步决策路由。

对外只暴露 Skill 类，实现 decide() 方法。
符合项目 agent.py 的接口约定：
    Skill.decide(user_input, llm_response, context, memory) -> dict

本文件是路由器，3 种决策模式的实际逻辑分别在各自的 skill 文件夹中：
  - skills/requirement-alignment/scripts/handle.py
  - skills/itinerary-planning/scripts/handle.py
  - skills/itinerary-validation/scripts/handle.py

决策策略：
  - 当用户输入包含旅行意图关键词、提到已知目的地、或处于行程规划/校验上下文中时，
    进入旅行 Skill 流程。
  - 否则视为通用聊天 / 知识问答，直接返回 LLM 生成的回复，不强制收集旅行槽位。

兼容两种 context 传入方式：
  - context 为 Context 对象：优先从 Context 读取/写入 slots 和 itinerary。
  - context 为 dict：保持旧行为，从 memory 读取 current_requirement / current_itinerary。
"""

import logging
from typing import Optional

from skills.common import utils, slot_extractor
from skills.common.models import UserRequirement
from skills.requirement_alignment.scripts import handle as alignment_handle
from skills.itinerary_planning.scripts import handle as planning_handle
from skills.itinerary_validation.scripts import handle as validation_handle
from skills.common import formatter
from rag import RAGTool

logger = logging.getLogger(__name__)


class Skill:
    """Skill 决策层主类。

    被 Agent.process_turn 调用：
        decision = self.skill.decide(user_input, llm_response, context, memory)
    返回决策字典，由 agent.py 执行。
    """

    # 触发 RAG 知识检索的疑问/知识表达模式
    RAG_QUESTION_PATTERNS = [
        "什么是", "为什么", "如何", "介绍一下", "告诉我", "请问",
        "是什么", "有哪些", "在哪里", "多少钱", "多久", "几点", "什么时候",
        "怎么办", "怎么做", "怎么查", "怎么用",
        "能帮我查", "帮我查一下", "根据文档", "查一下", "搜索一下",
        # 英文/数字类知识问法
        "what is", "what are", "how to", "how much", "how many",
        "why does", "explain", "tell me about", "according to",
        "百分之", "多少", "多大", "多快", "多远", "多久", "几岁",
        "对比", "比较", "区别", "差异", "优缺点", "哪个更好",
    ]

    # 明显闲聊，直接走 direct，不再询问 LLM
    CHITCHAT_PATTERNS = [
        "你好", "您好", "嗨", "hello", "hi", "hey",
        "谢谢", "感谢", "多谢", "thanks", "thank you",
        "再见", "拜拜", "bye", "goodbye",
        "哈哈", "呵呵", "嗯", "哦", "好", "好的", "ok", "okay",
        "随便", "聊点别的", "讲个笑话", "你是谁", "你能做什么",
    ]

    def __init__(self, model=None):
        self._rag: Optional[RAGTool] = None
        self.model = model

    @property
    def rag(self) -> RAGTool:
        """延迟初始化 RAGTool，避免在 Streamlit 启动时阻塞。"""
        if self._rag is None:
            self._rag = RAGTool()
        return self._rag

    def decide(self, user_input: str, llm_response: str,
               context, memory) -> dict:
        """单步决策入口（路由器）。

        Args:
            user_input: 用户本轮输入
            llm_response: Model.complete() 的原始响应（用于通用聊天直接回复）
            context: Context 对象或 dict
            memory: Memory 实例，有 store/retrieve 方法

        Returns:
            {"action": "direct", "response": str}
            或
            {"action": "tool", "tool": "generate_itinerary", "params": {...}}
            或
            {"action": "tool", "tool": "rag_retrieve", "params": {"query": ...}}
            或
            {"action": "direct", "response": str, "reset_context": True}
        """
        if self._is_context_obj(context):
            return self._decide_with_context(user_input, llm_response, context, memory)
        return self._decide_legacy(user_input, llm_response, context, memory)

    @staticmethod
    def _is_context_obj(context) -> bool:
        """判断 context 是否为具备 Context 类行为的对象。"""
        return (
            hasattr(context, "get_slots")
            and hasattr(context, "get_itinerary")
            and hasattr(context, "resolve_itinerary")
        )

    def _is_travel_intent(self, user_input: str, context, memory) -> bool:
        """判断当前输入是否为旅行相关请求。

        判断逻辑：
          1. 包含旅行意图关键词（如"旅游"、"行程"、"攻略"等）。
          2. 提到已知目的地（如"成都"、"云南"等）。
          3. 已有目的地槽位，且本轮补充旅行槽位（天数/预算/偏好）。
          4. 已有行程，且本轮请求校验/重新生成/查看行程。
        """
        # 1. 显式旅行关键词
        if utils.detect_intent(user_input, utils.TRAVEL_KEYWORDS):
            logger.info("[Skill] 命中旅行关键词 -> travel intent")
            return True

        # 2. 提到已知目的地
        new_req = slot_extractor.extract(user_input)
        if new_req.destination:
            logger.info("[Skill] 提取到目的地 '%s' -> travel intent", new_req.destination)
            return True

        # 3. 已有行程的后续操作
        has_itinerary = self._has_active_itinerary(context, memory)
        if has_itinerary and (
            utils.detect_intent(user_input, utils.VALIDATION_KEYWORDS)
            or utils.detect_intent(user_input, utils.REGENERATE_KEYWORDS)
            or utils.detect_intent(user_input, ["行程"])
        ):
            logger.info("[Skill] 已有行程 + 后续操作 -> travel intent")
            return True

        # 4. 处于旅行槽位收集流程中（已有目的地），本轮补充槽位
        current_req = self._get_current_requirement(context, memory)
        if current_req and current_req.destination:
            if any([new_req.days, new_req.budget, new_req.preferences]):
                logger.info("[Skill] 补充旅行槽位 -> travel intent")
                return True

        logger.debug("[Skill] 未命中旅行意图")
        return False

    def _is_rag_intent(self, user_input: str, context, memory) -> bool:
        """判断当前输入是否应触发 RAG 知识检索。

        两层路由：
          1. 规则快速通道：明显闲聊 -> 否；明显知识问答 -> 是。
          2. 模糊情况且有 LLM 可用时，用短 prompt 让模型二分类。
        """
        if not self.rag.enabled:
            return False

        # 旅行规划中不触发 RAG
        if self._has_active_itinerary(context, memory):
            return False
        current_req = self._get_current_requirement(context, memory)
        if current_req and current_req.destination:
            return False

        text = user_input.strip()
        if not text:
            return False

        # 1. 明显闲聊快速返回
        if utils.detect_intent(text, self.CHITCHAT_PATTERNS):
            logger.info("[Skill] 命中闲聊模式 -> direct")
            return False

        # 2. 明显知识问答快速返回
        if utils.detect_intent(text, self.RAG_QUESTION_PATTERNS):
            logger.info("[Skill] 命中 RAG 问答模式 -> rag intent")
            return True

        # 3. 模糊情况：用 LLM 做短分类（如果模型可用）
        if self.model is not None:
            return self._llm_classify_rag_intent(text, context)

        logger.info("[Skill] 未命中 RAG 模式 -> direct")
        return False

    def _llm_classify_rag_intent(self, user_input: str, context) -> bool:
        """用 LLM 对模糊查询做二分类：是否需要检索知识库。

        返回 True 表示应走 RAG，False 表示直接闲聊/通用问答。
        """
        try:
            summary = ""
            if context is not None and hasattr(context, "get"):
                summary = context.get().get("summary", "")

            prompt_lines = [
                "请判断下面这条用户消息，是否需要查询知识库才能回答。",
                "只回答一个单词：'rag'（需要查资料）或 'chat'（闲聊或通用常识即可）。",
                "",
            ]
            if summary:
                prompt_lines.append(f"对话摘要：{summary}")
            prompt_lines.extend([
                f"用户消息：{user_input}",
                "",
                "判断：",
            ])
            prompt = "\n".join(prompt_lines)

            resp = self.model.complete(prompt)
            label = resp.strip().lower().split()[0] if resp else "chat"
            is_rag = label in ("rag", "检索", "查资料", "知识库", "yes", "需要")
            logger.info("[Skill] LLM 意图分类 -> %s (raw=%s)", "rag" if is_rag else "chat", resp.strip())
            return is_rag
        except Exception as e:  # noqa: BLE001
            logger.debug("[Skill] LLM 分类失败，回退 direct: %s", e)
            return False

    def _has_active_itinerary(self, context, memory) -> bool:
        """判断当前是否存在有效行程。"""
        if self._is_context_obj(context):
            return context.resolve_itinerary(memory) is not None
        if memory is not None:
            return memory.retrieve("current_itinerary") is not None
        return False

    def _get_current_requirement(self, context, memory) -> UserRequirement | None:
        """读取当前已收集的旅行需求槽位。"""
        slots = {}
        if self._is_context_obj(context):
            slots = context.get_slots() or {}
        elif memory is not None:
            slots = memory.retrieve("current_requirement") or {}

        if not slots:
            return None
        return UserRequirement(
            destination=slots.get("destination"),
            days=slots.get("days"),
            budget=slots.get("budget"),
            budget_level=slots.get("budget_level", "mid"),
            preferences=slots.get("preferences"),
        )

    def _decide_with_context(self, user_input: str, llm_response: str,
                             context, memory) -> dict:
        """基于 Context 对象的决策分支。"""
        # 1. 检测重置意图
        if utils.detect_intent(user_input, utils.RESET_KEYWORDS):
            return {
                "action": "direct",
                "response": "好的，已清空之前的规划。请告诉我您想去哪里？",
                "reset_context": True,
            }

        # 2. 非旅行意图 → 直接返回 LLM 回复（通用聊天 / 知识问答）
        if not self._is_travel_intent(user_input, context, memory):
            # 2.1 若满足 RAG 知识检索条件，则调用 RAG 检索
            if self._is_rag_intent(user_input, context, memory):
                logger.info("[Skill] 决策 -> rag_retrieve")
                return {
                    "action": "tool",
                    "tool": "rag_retrieve",
                    "params": {"query": user_input, "top_k": 5},
                }
            logger.info("[Skill] 决策 -> direct (通用聊天)")
            return {"action": "direct", "response": llm_response}

        logger.info("[Skill] 进入旅行 Skill 流程")

        # 3. 提取并合并槽位（同时写入 Context.slots 和 Memory.current_requirement）
        current_req = utils.get_merged_requirement(user_input, context, memory)

        # 4. 读取当前行程（优先从 Context，必要时同步到 Memory 供旧 handle 使用）
        itinerary = context.resolve_itinerary(memory)
        has_itinerary = itinerary is not None

        # 5. 检测校验意图（已有行程时）
        if has_itinerary and utils.detect_intent(user_input, utils.VALIDATION_KEYWORDS):
            if memory is not None:
                memory.store("current_itinerary", itinerary)
            return validation_handle.handle(memory)

        # 6. 检测重新生成意图（已有行程时）
        if has_itinerary and utils.detect_intent(user_input, utils.REGENERATE_KEYWORDS):
            if current_req.is_complete():
                context.set_itinerary(None)
                if memory is not None:
                    memory.store("current_itinerary", None)
                return planning_handle.handle(current_req)
            return alignment_handle.handle(current_req)

        # 7. 已有行程时的处理
        if has_itinerary:
            # 7.1 用户本轮提供了新的目的地/天数/预算 → 视为重新规划
            new_req = slot_extractor.extract(user_input)
            if new_req.destination or new_req.days or new_req.budget:
                if current_req.is_complete():
                    context.set_itinerary(None)
                    if memory is not None:
                        memory.store("current_itinerary", None)
                    return planning_handle.handle(current_req)
                return alignment_handle.handle(current_req)

            # 7.2 无新需求 → 展示已有行程
            if memory is not None:
                memory.store("current_itinerary", itinerary)
            return {"action": "direct", "response": formatter.format_itinerary(itinerary)}

        # 8. 无行程 → 判断槽位是否齐全
        if not current_req.is_complete():
            return alignment_handle.handle(current_req)

        # 9. 槽位齐全 → 触发行程生成
        return planning_handle.handle(current_req)

    def _decide_legacy(self, user_input: str, llm_response: str,
                       context: dict, memory) -> dict:
        """兼容旧行为的决策分支（context 为 dict 时）。"""
        # 1. 从 memory 恢复已有行程（跨轮持久化）
        utils.restore_itinerary_from_memory(memory)

        # 2. 检测重置意图
        if utils.detect_intent(user_input, utils.RESET_KEYWORDS):
            if memory is not None:
                memory.store("current_requirement", None)
                memory.store("current_itinerary", None)
                memory.store("reset_flag", True)
            return {"action": "direct", "response": "好的，已清空之前的规划。请告诉我您想去哪里？"}

        # 3. 非旅行意图 → 直接返回 LLM 回复（通用聊天 / 知识问答）
        if not self._is_travel_intent(user_input, context, memory):
            # 3.1 若满足 RAG 知识检索条件，则调用 RAG 检索
            if self._is_rag_intent(user_input, context, memory):
                logger.info("[Skill] 决策 -> rag_retrieve")
                return {
                    "action": "tool",
                    "tool": "rag_retrieve",
                    "params": {"query": user_input, "top_k": 5},
                }
            logger.info("[Skill] 决策 -> direct (通用聊天)")
            return {"action": "direct", "response": llm_response}

        logger.info("[Skill] 进入旅行 Skill 流程")

        # 4. 提取并合并槽位
        current_req = utils.get_merged_requirement(user_input, context=None, memory=memory)

        # 5. 检测校验意图（已有行程时）
        has_itinerary = memory.retrieve("current_itinerary") is not None if memory else False
        if has_itinerary and utils.detect_intent(user_input, utils.VALIDATION_KEYWORDS):
            return validation_handle.handle(memory)

        # 6. 检测重新生成意图（已有行程时）
        if has_itinerary and utils.detect_intent(user_input, utils.REGENERATE_KEYWORDS):
            if current_req.is_complete():
                if memory is not None:
                    memory.store("current_itinerary", None)
                return planning_handle.handle(current_req)
            return alignment_handle.handle(current_req)

        # 7. 已有行程时的处理
        if has_itinerary:
            # 7.1 用户本轮提供了新的目的地/天数/预算 → 视为重新规划
            new_req = slot_extractor.extract(user_input)
            if new_req.destination or new_req.days or new_req.budget:
                if current_req.is_complete():
                    if memory is not None:
                        memory.store("current_itinerary", None)
                    return planning_handle.handle(current_req)
                return alignment_handle.handle(current_req)

            # 7.2 无新需求 → 展示已有行程
            itinerary = memory.retrieve("current_itinerary")
            return {"action": "direct", "response": formatter.format_itinerary(itinerary)}

        # 8. 无行程 → 判断槽位是否齐全
        if not current_req.is_complete():
            return alignment_handle.handle(current_req)

        # 9. 槽位齐全 → 触发行程生成
        return planning_handle.handle(current_req)
