"""LLM 厂商的 Provider 基类接口。"""

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """模型 Provider 的抽象基类。

    所有 Provider 必须实现 ``complete(prompt) -> str`` 方法。
    """

    def __init__(self, api_key: str, model_name: str, base_url: str | None = None):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """使用给定 prompt 调用模型并返回原始文本输出。"""
        ...
