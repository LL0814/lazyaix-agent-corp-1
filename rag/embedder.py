"""OpenAI 兼容 Embedding 客户端封装。

通过任意 OpenAI 兼容接口 ``/v1/embeddings`` 获取稠密向量。
默认使用阿里云百炼（DashScope）通义 Embedding，可通过环境变量切换到
其他兼容服务（如 Ollama、SiliconFlow、OpenAI 等）。

当服务不可达或模型未下载时，方法返回空列表并记录告警，
不抛出异常中断上层流程。
"""

import logging
import time
from typing import List, Optional

try:
    from openai import OpenAI, APIError, APITimeoutError
except ImportError:  # pragma: no cover
    OpenAI = None
    APIError = Exception
    APITimeoutError = Exception

logger = logging.getLogger(__name__)


class Embedder:
    """OpenAI 兼容 Embedding 客户端。

    Attributes:
        base_url: API 基础地址，例如
            ``https://dashscope.aliyuncs.com/compatible-mode/v1``。
        api_key: API 密钥。
        model: 模型名，例如 ``text-embedding-v4``。
        dim: 输出向量维度，默认 1024（text-embedding-v4 / bge-m3）。
    """

    DEFAULT_DIM = 1024
    REQUEST_TIMEOUT = 60

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int = DEFAULT_DIM,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "not-set"
        self.model = model
        self.dim = dim
        self._client: Optional[OpenAI] = None
        if OpenAI is not None:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )

    def embed(self, text: str) -> List[float]:
        """单文本向量化。

        Args:
            text: 输入文本。

        Returns:
            dim 维浮点向量；失败时返回空列表。
        """
        if not text:
            return []
        result = self.embed_batch([text], batch_size=1)
        return result[0] if result else []

    def embed_batch(self, texts: List[str], batch_size: int = 8) -> List[List[float]]:
        """批量向量化。

        Args:
            texts: 输入文本列表。
            batch_size: 每批大小，默认 8。

        Returns:
           与 ``texts`` 长度一致的向量列表；失败的文本对应空列表。
        """
        if not texts:
            return []

        if self._client is None:
            logger.warning("[RAG] openai 包未安装，无法调用 Embedding API")
            return [[] for _ in texts]

        batch_size = max(1, batch_size)
        results: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_results = self._embed_with_retry(batch)
            results.extend(batch_results)
        return results

    def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """带一次重试的批量嵌入请求。"""
        for attempt in range(2):
            try:
                response = self._client.embeddings.create(
                    model=self.model,
                    input=texts,
                    timeout=self.REQUEST_TIMEOUT,
                )
                return self._parse_response(response, len(texts))
            except APITimeoutError as e:
                logger.warning("[RAG] Embedding API 超时 (%s): %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(1)
                    continue
            except APIError as e:
                message = str(e).lower()
                if "not found" in message or "model" in message:
                    logger.warning(
                        "[RAG] Embedding 模型 %s 未找到或不可用",
                        self.model,
                    )
                else:
                    logger.warning("[RAG] Embedding API 错误: %s", e)
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("[RAG] Embedding 请求异常: %s", e)
                break
        return [[] for _ in texts]

    def _parse_response(self, response, expected_count: int) -> List[List[float]]:
        """解析 OpenAI Embedding 响应，校验维度。"""
        try:
            data = response.data
            if not data or len(data) != expected_count:
                logger.warning(
                    "[RAG] Embedding 返回数量异常: 期望 %d，实际 %d",
                    expected_count, len(data) if data else 0,
                )
                return [[] for _ in range(expected_count)]

            results = []
            for item in data:
                vec = list(item.embedding)
                if len(vec) != self.dim:
                    logger.warning(
                        "[RAG] Embedding 维度异常: 期望 %d，实际 %d",
                        self.dim, len(vec),
                    )
                    results.append([])
                else:
                    results.append(vec)
            return results
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Embedding 响应解析失败: %s", e)
            return [[] for _ in range(expected_count)]
