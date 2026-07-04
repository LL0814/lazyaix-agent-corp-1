"""LLM 厂商的 Provider 基类接口。"""

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """模型 Provider 的抽象基类。

    所有 Provider 必须实现 ``complete(prompt) -> str`` 方法。
    ``complete_with_tools`` 为可选方法，用于支持 LLM 意图识别与工具调用决策。
    """

    def __init__(self, api_key: str, model_name: str, base_url: str | None = None):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """使用给定 prompt 调用模型并返回原始文本输出。"""
        ...

    def complete_with_tools(
        self,
        prompt: str,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> str:
        """调用模型并允许其参考可用工具列表进行决策。

        默认实现退化为 complete()，子类可覆写以支持原生 function calling。
        本方法返回模型的文本输出；调用方需自行解析决策（如 JSON）。
        """
        return self.complete(prompt, system=system)
