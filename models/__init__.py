"""Model module: loads configuration and provides LLM complete().

当前实现默认对接 DeepSeek（OpenAI 兼容接口），模型名称可通过环境变量
``MODEL_NAME`` 配置，例如 ``deepseek-v4-pro``。
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class Model:
    """封装 DeepSeek/OpenAI 兼容接口，提供 ``complete(prompt)`` 方法。"""

    def __init__(self) -> None:
        self.api_key = os.environ.get("MODEL_API_KEY", "stub-key")
        self.model_name = os.environ.get("MODEL_NAME", "deepseek-v4-pro")
        self.base_url = os.environ.get(
            "MODEL_BASE_URL", "https://api.deepseek.com"
        )
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        """延迟初始化 OpenAI 客户端。"""
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def complete(self, prompt: str) -> str:
        """调用 LLM 并返回原始文本输出。

        若未配置真实 API Key（仍为 stub-key）或调用失败，则回退到本地 stub
        输出，避免项目在没有网络/Key 时直接报错。
        """
        if self.api_key in ("stub-key", "", None):
            return f"[{self.model_name}] {prompt}"

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            content = response.choices[0].message.content
            return content if content is not None else ""
        except Exception as exc:  # noqa: BLE001
            return f"[{self.model_name}] API error: {exc}\nStub fallback: {prompt}"
