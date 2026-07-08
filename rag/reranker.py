"""OpenAI 兼容 Reranker 客户端封装。

通过 OpenAI 兼容 ``/reranks`` 端点对候选文本进行相关性重排序。
默认适配阿里云百炼（DashScope）通义 Rerank 接口，也可用于其他兼容
Jina/Cohere 风格 rerank 的服务。

当服务不可用时返回原始顺序，不抛出异常。
"""

import json
import logging
import ssl
import time
from typing import List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class Reranker:
    """OpenAI 兼容 Reranker 客户端。

    Attributes:
        base_url: API 基础地址，例如
            ``https://dashscope.aliyuncs.com/compatible-api/v1``。
        api_key: API 密钥。
        model: Reranker 模型名，例如 ``qwen3-rerank``。
        rerank_path: rerank 端点路径，默认 ``/reranks``（DashScope/通义）。
    """

    REQUEST_TIMEOUT = 60
    DEFAULT_RERANK_PATH = "/reranks"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        rerank_path: str = DEFAULT_RERANK_PATH,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.rerank_path = rerank_path

    def rerank(self, query: str, passages: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        """对 passages 按与 query 的相关性重排序。

        Args:
            query: 查询文本。
            passages: 候选文本列表。
            top_k: 返回前 k 个结果。

        Returns:
            [(原始索引, 分数), ...]，按分数降序排列。
            若服务不可用，返回按索引顺序的前 top_k 项，分数均为 0.0。
        """
        if not passages:
            return []

        if not query:
            return [(i, 0.0) for i in range(min(top_k, len(passages)))]

        try:
            results = self._rerank_with_retry(query, passages, top_k)
            if not results:
                return [(i, 0.0) for i in range(min(top_k, len(passages)))]

            # results: [{"index": int, "relevance_score": float}, ...]
            ranked = [
                (int(item["index"]), float(item["relevance_score"]))
                for item in results
                if "index" in item and "relevance_score" in item
            ]
            ranked.sort(key=lambda x: x[1], reverse=True)
            return ranked[:top_k]
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Reranker 执行异常: %s", e)
            return [(i, 0.0) for i in range(min(top_k, len(passages)))]

    def _rerank_with_retry(
        self, query: str, passages: List[str], top_k: int
    ) -> List[dict]:
        """带一次重试的 rerank 请求。"""
        url = f"{self.base_url}{self.rerank_path}"
        payload = {
            "model": self.model,
            "query": query,
            "documents": passages,
            "top_n": min(top_k, len(passages)),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )

        for attempt in range(2):
            try:
                with urlopen(req, timeout=self.REQUEST_TIMEOUT, context=_SSL_CONTEXT) as resp:
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    return self._parse_response(data)
            except URLError as e:
                logger.debug("[RAG] Reranker 服务不可达: %s", url)
                if attempt == 0:
                    time.sleep(1)
                    continue
                break
            except json.JSONDecodeError as e:
                logger.warning("[RAG] Reranker 响应解析失败: %s", e)
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("[RAG] Reranker 请求异常: %s", e)
                break
        return []

    @staticmethod
    def _parse_response(data: dict) -> List[dict]:
        """解析 rerank 响应，兼容顶层 results 与 output.results 两种格式。"""
        results = data.get("results")
        if results is None:
            output = data.get("output") or {}
            results = output.get("results")
        if not results:
            logger.warning("[RAG] Reranker 返回结果为空")
            return []
        return list(results)
