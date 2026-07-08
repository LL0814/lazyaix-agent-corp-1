"""多路检索器：融合 Milvus 向量、全文、混合与元数据过滤召回。"""

import logging
from typing import List, Dict, Optional

from .milvus_client import MilvusClient
from .embedder import Embedder

logger = logging.getLogger(__name__)


class Retriever:
    """五路检索器。

    路1: 稠密向量检索（COSINE）
    路2: 稠密向量检索（IP）
    路3: 全文关键词检索（BM25）
    路4: 混合检索（Dense + Sparse）
    路5: 元数据过滤检索
    """

    def __init__(self, milvus_client: MilvusClient, embedder: Embedder):
        self.milvus = milvus_client
        self.embedder = embedder

    def multi_search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[dict] = None,
    ) -> List[List[str]]:
        """执行 5 路召回，返回 5 个 doc_id 列表。

        Args:
            query: 查询文本。
            top_k: 每路取 top-k 个结果。
            filters: 元数据过滤条件，例如 {"city": "成都"}。

        Returns:
            5 个 doc_id 排名列表，按相关性降序排列。
        """
        if not query:
            return [[] for _ in range(5)]

        query_vec = self.embedder.embed(query)
        if not query_vec:
            logger.warning("[RAG] 查询向量化失败，所有向量检索路返回空结果")
            return [[] for _ in range(5)]

        logger.debug("[RAG] 开始五路召回: top_k=%d, filters=%s", top_k, filters)
        ranked_lists = [
            self._route1_dense_cosine(query_vec, top_k),
            self._route2_dense_ip(query_vec, top_k),
            self._route3_fulltext(query, top_k),
            self._route4_hybrid(query_vec, query, top_k, filters),
            self._route5_filtered(query_vec, top_k, filters),
        ]
        logger.debug(
            "[RAG] 五路召回结果数: cosine=%d, ip=%d, bm25=%d, hybrid=%d, filtered=%d",
            len(ranked_lists[0]), len(ranked_lists[1]), len(ranked_lists[2]),
            len(ranked_lists[3]), len(ranked_lists[4]),
        )
        return ranked_lists

    def _route1_dense_cosine(self, query_vec: List[float], top_k: int) -> List[str]:
        """路1: 稠密向量检索（COSINE）。"""
        results = self.milvus.search([query_vec], top_k=top_k, metric_type="COSINE")
        return self._extract_ids(results[0]) if results else []

    def _route2_dense_ip(self, query_vec: List[float], top_k: int) -> List[str]:
        """路2: 稠密向量检索（IP 退化为 COSINE，与索引保持一致）。"""
        results = self.milvus.search([query_vec], top_k=top_k, metric_type="COSINE")
        return self._extract_ids(results[0]) if results else []

    def _route3_fulltext(self, query: str, top_k: int) -> List[str]:
        """路3: 全文关键词检索（BM25）。"""
        results = self.milvus.text_search(query, top_k=top_k)
        return self._extract_ids(results)

    def _route4_hybrid(
        self,
        query_vec: List[float],
        query: str,
        top_k: int,
        filters: Optional[dict],
    ) -> List[str]:
        """路4: 混合检索（Dense + Sparse）。"""
        sparse_vec = self._encode_sparse([query])
        if not sparse_vec:
            return []
        expr = self._build_filter_expr(filters)
        results = self.milvus.hybrid_search(
            dense_vectors=[query_vec],
            sparse_vectors=sparse_vec,
            top_k=top_k,
            expr=expr,
        )
        return self._extract_ids(results[0]) if results else []

    def _route5_filtered(
        self,
        query_vec: List[float],
        top_k: int,
        filters: Optional[dict],
    ) -> List[str]:
        """路5: 元数据过滤检索。"""
        expr = self._build_filter_expr(filters)
        if not expr:
            # 无过滤条件时退化为路1
            return self._route1_dense_cosine(query_vec, top_k)
        results = self.milvus.search(
            [query_vec], top_k=top_k, metric_type="COSINE", expr=expr,
        )
        return self._extract_ids(results[0]) if results else []

    @staticmethod
    def _extract_ids(results: List[Dict]) -> List[str]:
        """从 Milvus 搜索结果中提取 doc_id 列表并去重。"""
        seen = set()
        ids = []
        for hit in results:
            doc_id = hit.get("id")
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                ids.append(doc_id)
        return ids

    @staticmethod
    def _build_filter_expr(filters: Optional[dict]) -> str:
        """将过滤字典转换为 Milvus expr 表达式。"""
        if not filters:
            return ""
        conditions = []
        for key, value in filters.items():
            if value is None:
                continue
            safe_key = "".join(c for c in str(key) if c.isalnum() or c == "_")
            safe_value = str(value).replace('"', '\\"')
            conditions.append(f'{safe_key} == "{safe_value}"')
        return " && ".join(conditions)

    def _encode_sparse(self, texts: List[str]):
        """使用 BM25 将文本编码为稀疏向量。"""
        return self.milvus._bm25_encode(texts)
