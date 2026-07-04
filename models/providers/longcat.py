"""美团 LongCat Provider，使用 OpenAI 兼容接口。"""

from .openai_compatible import OpenAICompatibleProvider


class LongCatProvider(OpenAICompatibleProvider):
    """美团 LongCat 大模型 Provider（LongCat-2.0）。

    端点与模型名参考 LongCat API 开放平台文档：
    https://longcat.chat/platform/docs/zh/
    """

    provider_label = "longcat"
    default_base_url = "https://api.longcat.chat/openai"
    supported_models = ["LongCat-2.0"]
