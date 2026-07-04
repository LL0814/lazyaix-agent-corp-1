"""Skill 插件注册表。

管理所有已注册的 SkillPlugin 实例，提供：
  - register(plugin): 注册插件
  - get(name): 按名获取插件
  - all(): 获取全部插件
  - match(user_input): 用规则兜底匹配插件（LLM 不可用时使用）
  - all_tool_specs(): 汇总所有插件的工具规格（供 LLM 决策）
"""

from .base import SkillPlugin


class SkillRegistry:
    """Skill 插件注册中心。"""

    def __init__(self):
        self._plugins: dict[str, SkillPlugin] = {}

    def register(self, plugin: SkillPlugin) -> None:
        """注册一个 Skill 插件。"""
        if not plugin.name:
            raise ValueError("插件必须设置 name 属性")
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> SkillPlugin | None:
        """按名获取插件。"""
        return self._plugins.get(name)

    def all(self) -> list[SkillPlugin]:
        """获取全部已注册插件。"""
        return list(self._plugins.values())

    def match(self, user_input: str) -> SkillPlugin | None:
        """规则兜底：返回首个关键词命中的插件。"""
        for plugin in self._plugins.values():
            if plugin.matches(user_input):
                return plugin
        return None

    def all_tool_specs(self) -> list[dict]:
        """汇总所有插件的工具规格（带 source 标识归属插件）。"""
        specs: list[dict] = []
        for plugin in self._plugins.values():
            for tool in plugin.get_tool_specs():
                spec = dict(tool)
                spec["source_skill"] = plugin.name
                specs.append(spec)
        return specs


# 全局默认注册表（agent.py 启动时用）
default_registry = SkillRegistry()
