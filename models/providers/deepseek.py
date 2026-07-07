"""DeepSeek Provider using an OpenAI-compatible interface."""

from .openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek model provider."""

    provider_label = "deepseek"
    default_base_url = "https://api.deepseek.com"
    supported_models: list[str] = []
