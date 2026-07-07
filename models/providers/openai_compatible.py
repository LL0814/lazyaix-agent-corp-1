"""OpenAI 兼容接口的 Provider 基类。"""

import json

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
        effective_base_url = base_url or self.default_base_url
        super().__init__(api_key, model_name, effective_base_url)
        # 当 API Key 缺失时延迟构建客户端，
        # 以便 Agent 仍能启动并在请求时给出友好提示。
        if api_key:
            self._client = OpenAI(
                api_key=api_key,
                base_url=effective_base_url,
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

    def complete_with_tools(
        self,
        prompt: str,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> str:
        """调用模型，附带可用工具列表供 LLM 决策参考。

        采用 JSON 格式约束方案：把工具列表拼到 system prompt 中，
        要求 LLM 输出 JSON 决策。不依赖原生 function calling，
        兼容所有 OpenAI 兼容端点（包括 Kimi）。

        Args:
            prompt: 用户输入
            tools: 可用工具列表，每项形如 {"name":..., "description":..., "params":...}
            system: 额外 system 指令

        Returns:
            模型文本输出（调用方需自行解析 JSON 决策）
        """
        if not tools:
            return self.complete(prompt, system=system)

        tools_desc = json.dumps(tools, ensure_ascii=False, indent=2)
        decision_system = (
            "你是一个智能助手的决策模块。根据用户输入，从可用工具中选择最合适的一个调用，"
            "或直接回答。\n\n"
            f"可用工具列表：\n{tools_desc}\n\n"
            "请严格按以下 JSON 格式输出（不要包含其他内容，不要 markdown 代码块）：\n"
            '{"action": "direct", "response": "直接回复内容"}\n'
            "或\n"
            '{"action": "tool", "tool": "工具名", "params": {"参数名": "值"}}\n\n'
            "规则：\n"
            "1. 如果用户问题与可用工具无关，用 direct 直接回答\n"
            "2. 如果需要调用工具，选最匹配的一个，并提取合理参数\n"
            "3. 输出必须是合法 JSON，不要有任何额外文本"
        )
        if system:
            decision_system = system + "\n\n" + decision_system
        return self.complete(prompt, system=decision_system)
