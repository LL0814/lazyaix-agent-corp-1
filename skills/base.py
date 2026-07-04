"""Skill 插件抽象基类。

每个 Skill 插件是一个可插拔的能力单元，需实现：
  - name: 插件标识（用于 LLM 路由识别）
  - description: 插件描述（供 LLM 判断何时调用）
  - keywords: 触发关键词列表（用于规则兜底匹配）
  - tools: 该插件可用的工具列表（供 LLM 决策参考）
  - handle(user_input, llm_response, context, memory, tool_executor): 处理逻辑

通用 Agent 启动时，把所有已注册插件的信息汇总给 LLM，
LLM 决定调用哪个插件；若 LLM 不可用，则用 keywords 做规则兜底。
"""

from typing import Callable, Protocol


class ToolExecutor(Protocol):
    """Tool 执行器协议（agent.py 的 Tool 实例满足此协议）。"""
    def execute(self, action: str, params: dict) -> object: ...


class SkillPlugin:
    """Skill 插件基类。

    子类应设置 name / description / keywords / tools，
    并实现 handle() 方法返回决策 dict。
    """

    name: str = ""
    description: str = ""
    keywords: list[str] = []
    tools: list[dict] = []  # 形如 [{"name":..., "description":..., "params": {...}}]

    def handle(
        self,
        user_input: str,
        llm_response: str,
        context: dict,
        memory,
        tool_executor: ToolExecutor | None = None,
    ) -> dict:
        """处理用户输入，返回决策 dict。

        决策格式：
          {"action": "direct", "response": "..."}
          {"action": "tool", "tool": "...", "params": {...}}
        """
        raise NotImplementedError

    def matches(self, user_input: str) -> bool:
        """规则兜底：检查用户输入是否命中本插件的关键词。"""
        if not self.keywords:
            return False
        lowered = user_input.lower()
        return any(kw in user_input or kw in lowered for kw in self.keywords)

    def get_tool_specs(self) -> list[dict]:
        """返回本插件提供的工具规格（供 LLM 决策参考）。"""
        return self.tools
