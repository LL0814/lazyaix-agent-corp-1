"""Kimi（月之暗面）Provider，使用 OpenAI 兼容接口。"""

from .openai_compatible import OpenAICompatibleProvider


class KimiProvider(OpenAICompatibleProvider):
    """月之暗面 Kimi / Moonshot 模型 Provider。"""

    provider_label = "kimi"
    default_base_url = "https://api.moonshot.cn/v1"
    supported_models = [
        "kimi-k2.7-code-highspeed",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "kimi-k2.5",
        "moonshot-v1-auto",
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ]
