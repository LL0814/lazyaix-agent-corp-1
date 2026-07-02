"""模型入口：加载配置并暴露 LLM complete() 方法。"""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .factory import ProviderFactory
from .providers.base import BaseProvider


class Model:
    """统一 LLM 包装器。

    从环境变量读取 ``MODEL``（格式 ``provider:model``），并解析对应厂商的
    API Key / Base URL：

    - ``TONGYI_API_KEY`` / ``TONGYI_BASE_URL``
    - ``GLM_API_KEY`` / ``GLM_BASE_URL``

    支持运行时通过 ``switch(model_spec)`` 切换模型。
    """

    DEFAULT_MODEL = "tongyi:qwen-turbo"

    def __init__(self):
        provider, model_name = self._parse_model_spec(
            os.environ.get("MODEL", self.DEFAULT_MODEL)
        )
        self.provider_name = provider
        self.model_name = model_name

        self.api_key, self.base_url = self._resolve_env_config(provider)

        self._provider: BaseProvider = ProviderFactory.create(
            provider=self.provider_name,
            api_key=self.api_key,
            model_name=self.model_name,
            base_url=self.base_url,
        )

    @staticmethod
    def _resolve_env_config(provider: str) -> tuple[str, str | None]:
        """解析 ``provider`` 对应的 API Key 和 Base URL。

        仅使用 ``{PROVIDER}_API_KEY`` / ``{PROVIDER}_BASE_URL`` 环境变量。
        没有通用回退 Key；运行时切换时必须使用目标厂商自身的凭据。

        类似 ``请在此填写...`` 的占位值将被视为未配置，
        以便 Agent 能给出明确的“Key 缺失”提示，而不是将无效 Key
        发送给厂商 API。
        """
        prefix = provider.upper()
        raw_key = os.environ.get(f"{prefix}_API_KEY", "")
        api_key = "" if "请在此" in raw_key else raw_key
        base_url = os.environ.get(f"{prefix}_BASE_URL", "") or None
        return api_key, base_url

    @staticmethod
    def _parse_model_spec(spec: str) -> tuple[str, str]:
        """将 ``provider:model`` 格式的字符串解析为 (provider, model_name)。"""
        spec = spec.strip()
        if ":" not in spec:
            raise ValueError(
                f"MODEL 格式错误，应为 provider:model，当前: {spec!r}"
            )
        provider, model_name = spec.split(":", 1)
        provider = provider.strip().lower()
        model_name = model_name.strip()
        if not provider or not model_name:
            raise ValueError(
                f"MODEL 格式错误，provider 和 model_name 不能为空: {spec!r}"
            )
        return provider, model_name

    def complete(self, prompt: str, system: str | None = None) -> str:
        """调用当前 Provider 并返回原始文本输出。"""
        return self._provider.complete(prompt, system=system)

    def switch(self, model_spec: str) -> bool:
        """运行时切换当前模型。

        Args:
            model_spec: 新模型，格式为 ``provider:model``。

        Returns:
            切换成功返回 True，否则返回 False。
        """
        try:
            provider, model_name = self._parse_model_spec(model_spec)
            api_key, base_url = self._resolve_env_config(provider)
            self._provider = ProviderFactory.create(
                provider=provider,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
            )
            self.provider_name = provider
            self.model_name = model_name
            self.api_key = api_key
            self.base_url = base_url
            return True
        except Exception as exc:
            print(f"[model] 切换失败：{exc}")
            return False
