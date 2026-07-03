"""Kimi（月之暗面）Provider，使用 OpenAI 兼容接口。"""

from .openai_compatible import OpenAICompatibleProvider


class KimiProvider(OpenAICompatibleProvider):
    """月之暗面 Kimi 模型 Provider（kimi-for-coding）。"""

    provider_label = "kimi"
    default_base_url = "https://api.kimi.com/coding/v1"
    supported_models = ["kimi-for-coding"]
