"""通用 Skill 路由主类：LLM 意图识别 + 规则兜底。

对外仍暴露 Skill 类，保持 agent.py 调用接口不变：
    Skill.decide(user_input, llm_response, context, memory) -> dict

工作流程：
  1. 用 Model.complete_with_tools 把用户输入 + 已注册插件信息给 LLM
  2. LLM 输出 JSON 决策（direct 直接回答 / tool 调用工具 / skill 调用子插件）
  3. 若 LLM 决策为某个 skill，委托给该插件的 handle()
  4. 若 LLM 不可用或输出非法，fallback 到规则关键词匹配

旅游行程规划作为默认插件内置注册，未来加新 skill 只需在 register_default_skills() 里注册。
"""

import json
import logging

from .base import SkillPlugin, ToolExecutor
from .registry import default_registry, SkillRegistry
from .travel_plugin import TravelSkill

logger = logging.getLogger(__name__)


def register_default_skills(registry: SkillRegistry) -> None:
    """注册内置默认 skill 插件。"""
    registry.register(TravelSkill())


# 模块加载时自动注册默认插件
register_default_skills(default_registry)


class Skill:
    """通用 Skill 路由主类。

    被 Agent.process_turn 调用：
        decision = self.skill.decide(user_input, llm_response, context, memory)

    支持两种路由模式：
      1. LLM 意图识别（需注入 model）：把插件信息给 LLM，由 LLM 决策
      2. 规则兜底（LLM 不可用时）：用插件 keywords 关键词匹配
    """

    def __init__(self, model=None, registry: SkillRegistry | None = None):
        """初始化通用 Skill 路由器。

        Args:
            model: Model 实例（可选）。传入则启用 LLM 意图识别；
                   不传则纯靠规则关键词匹配（测试/离线可用）。
            registry: Skill 注册表。默认用全局 default_registry。
        """
        self.model = model
        self.registry = registry or default_registry

    def decide(self, user_input: str, llm_response: str,
               context: dict, memory) -> dict:
        """单步决策入口。

        优先用 LLM 意图识别；LLM 不可用或输出非法时 fallback 到规则匹配。
        """
        # 1. 尝试 LLM 意图识别
        if self.model is not None:
            decision = self._decide_via_llm(user_input, llm_response, context, memory)
            if decision is not None:
                return decision
            logger.info("LLM 决策失败，回退到规则匹配")

        # 2. 规则兜底
        return self._decide_via_rules(user_input, llm_response, context, memory)

    def _decide_via_llm(
        self, user_input: str, llm_response: str, context: dict, memory
    ) -> dict | None:
        """用 LLM 做意图识别与工具选择。

        返回决策 dict；解析失败返回 None（由调用方 fallback）。
        """
        try:
            tool_specs = self.registry.all_tool_specs()
            if not tool_specs:
                # 没有注册任何插件/工具 → 直接用 LLM 原始回复
                return {"action": "direct", "response": llm_response}

            raw = self.model.complete_with_tools(
                prompt=user_input,
                tools=tool_specs,
                system="你是一个通用智能助手。根据用户输入决定直接回答还是调用工具。",
            )
            return self._parse_llm_decision(raw, user_input, llm_response, context, memory)
        except Exception as exc:
            logger.warning("LLM 意图识别异常: %s", exc)
            return None

    def _parse_llm_decision(
        self, raw: str, user_input: str, llm_response: str,
        context: dict, memory,
    ) -> dict | None:
        """解析 LLM 输出的 JSON 决策。

        支持三种决策：
          {"action": "direct", "response": "..."}
          {"action": "tool", "tool": "...", "params": {...}}
          {"action": "skill", "skill": "插件名", ...}  → 委托给插件 handle()
        """
        if not raw:
            return None

        # 尝试提取 JSON（LLM 可能包裹在 markdown 代码块或附加文字中）
        text = raw.strip()
        if text.startswith("```"):
            # 去掉 markdown 代码块
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])

        # 尝试找到第一个 { 和最后一个 } 之间的内容
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            # 不是 JSON，当作直接回复
            return {"action": "direct", "response": raw}
        json_str = text[start:end + 1]

        try:
            decision = json.loads(json_str)
        except json.JSONDecodeError:
            return {"action": "direct", "response": raw}

        action = decision.get("action")
        if action == "direct":
            response = decision.get("response") or llm_response
            return {"action": "direct", "response": response}
        if action == "tool":
            return {
                "action": "tool",
                "tool": decision.get("tool", ""),
                "params": decision.get("params", {}),
            }
        if action == "skill":
            plugin_name = decision.get("skill", "")
            plugin = self.registry.get(plugin_name)
            if plugin is None:
                return None
            return plugin.handle(user_input, llm_response, context, memory)

        # 未知 action，当作直接回复
        return {"action": "direct", "response": llm_response}

    def _decide_via_rules(
        self, user_input: str, llm_response: str, context: dict, memory
    ) -> dict:
        """规则兜底：用关键词匹配插件。"""
        plugin = self.registry.match(user_input)
        if plugin is not None:
            return plugin.handle(user_input, llm_response, context, memory)
        # 无插件命中 → 直接返回 LLM 原始回复
        return {"action": "direct", "response": llm_response}
