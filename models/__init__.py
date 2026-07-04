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
    """封装 DeepSeek/OpenAI 兼容接口，提供 LLM 调用方法。"""

    def __init__(self) -> None:
        self.api_key = os.environ.get("MODEL_API_KEY", "stub-key")
        self.model_name = os.environ.get("MODEL_NAME", "deepseek-v4-pro")
        self.base_url = os.environ.get(
            "MODEL_BASE_URL", "https://api.deepseek.com"
        )
        self.max_tokens = self._env_int("MODEL_MAX_TOKENS", 800)
        self.stream_max_chars = self._env_int("MODEL_STREAM_MAX_CHARS", 6000)
        self._client: OpenAI | None = None

    def _env_int(self, key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default

    def _completion_options(self, prompt: str, stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        if self.max_tokens > 0:
            options["max_tokens"] = self.max_tokens
        return options

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
                **self._completion_options(prompt, stream=False),
            )
            content = response.choices[0].message.content
            return content if content is not None else ""
        except Exception as exc:  # noqa: BLE001
            return f"[{self.model_name}] API error: {exc}\nStub fallback: {prompt}"

    def stream_complete(self, prompt: str):
        """流式调用 LLM，逐段产出文本。"""
        if self.api_key in ("stub-key", "", None):
            yield self.complete(prompt)
            return

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                **self._completion_options(prompt, stream=True),
            )
            streamed_chars = 0
            for event in response:
                content = event.choices[0].delta.content
                if content:
                    streamed_chars += len(content)
                    yield content
                if self.stream_max_chars > 0 and streamed_chars >= self.stream_max_chars:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                    return
        except Exception as exc:  # noqa: BLE001
            yield f"[{self.model_name}] API error: {exc}\nStub fallback: {prompt}"
