"""根据厂商名称创建 Provider 实例的工厂。"""

from .providers.base import BaseProvider
from .providers.glm import GLMProvider
from .providers.tongyi import TongyiProvider


class ProviderFactory:
    """根据给定的厂商标识创建对应的 BaseProvider 子类实例。"""

    _registry: dict[str, type[BaseProvider]] = {
        "tongyi": TongyiProvider,
        "glm": GLMProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
    ) -> BaseProvider:
        """创建 Provider 实例。

        Args:
            provider: 厂商标识，例如 ``tongyi`` 或 ``glm``。
            api_key: 厂商的 API 密钥。
            model_name: 具体模型名称，例如 ``qwen-turbo``。
            base_url: 可选的自定义 Base URL；不传则使用厂商默认地址。

        Raises:
            ValueError: 当该厂商未注册时抛出。
        """
        provider_cls = cls._registry.get(provider)
        if provider_cls is None:
            raise ValueError(f"不支持的模型厂商: {provider}")
        supported = getattr(provider_cls, "supported_models", None) or []
        if supported and model_name not in supported:
            raise ValueError(
                f"不支持的模型名称: {model_name}。"
                f"{provider} 支持的模型: {', '.join(supported)}"
            )
        if base_url is None:
            base_url = getattr(provider_cls, "default_base_url", None)
        return provider_cls(api_key=api_key, model_name=model_name, base_url=base_url)

    @classmethod
    def register(cls, name: str, provider_cls: type[BaseProvider]) -> None:
        """将新的 Provider 类以指定厂商名称注册到工厂中。"""
        if not issubclass(provider_cls, BaseProvider):
            raise TypeError("Provider class must inherit from BaseProvider")
        cls._registry[name] = provider_cls
