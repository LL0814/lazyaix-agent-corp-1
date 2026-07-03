"""通义千问（阿里云百炼）Provider，使用 OpenAI 兼容接口。"""

from .openai_compatible import OpenAICompatibleProvider


class TongyiProvider(OpenAICompatibleProvider):
    """阿里云通义千问模型 Provider（例如 qwen-turbo）。"""

    provider_label = "tongyi"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    supported_models = ["qwen-turbo", "qwen-plus", "qwen-max"]
