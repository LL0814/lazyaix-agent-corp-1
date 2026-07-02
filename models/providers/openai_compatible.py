"""OpenAI 兼容接口的 Provider 基类。"""

from openai import APITimeoutError, OpenAI

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """使用 OpenAI 兼容 chat 接口的 Provider 基类。

    子类必须定义 ``provider_label`` 和 ``default_base_url``。
    ``supported_models`` 为可选字段；非空时仅接受列表中的模型名称。
    """

    provider_label: str = ""
    default_base_url: str = ""
    supported_models: list[str] = []

    def __init__(self, api_key: str, model_name: str, base_url: str | None = None):
        super().__init__(api_key, model_name, base_url)
        # 当 API Key 缺失时延迟构建客户端，
        # 以便 Agent 仍能启动并在请求时给出友好提示。
        if api_key:
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url or self.default_base_url,
            )
        else:
            self._client = None

    def complete(self, prompt: str, system: str | None = None) -> str:
        """使用给定 prompt 调用模型并返回原始文本输出。"""
        label = self.provider_label
        if self._client is None:
            return f"[{label}] API Key 配置异常，请检查 .env"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = self._client.chat.completions.create(
                model=self.model_name,
                messages=messages,
            )
            content = resp.choices[0].message.content
            if content is None:
                return f"[{label}] 模型未返回有效内容"
            return content
        except (APITimeoutError, TimeoutError):
            return f"[{label}] 模型调用超时，请稍后重试"
        except Exception as e:
            return f"[{label}] 模型调用失败：{e}"
