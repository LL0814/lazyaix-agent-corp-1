"""智谱 GLM Provider，使用 OpenAI 兼容接口。"""

from .openai_compatible import OpenAICompatibleProvider


class GLMProvider(OpenAICompatibleProvider):
    """智谱 AI GLM 模型 Provider（例如 glm-4-flash）。"""

    provider_label = "glm"
    default_base_url = "https://open.bigmodel.cn/api/paas/v4/"
    supported_models = ["glm-4-flash", "glm-4", "glm-4-air"]
