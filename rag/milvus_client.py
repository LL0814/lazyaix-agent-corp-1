"""Milvus 向量数据库客户端。

负责连接 Milvus、维护 Collection Schema/Index、提供向量检索与文档管理能力。
当 pymilvus 未安装或服务不可达时，所有方法返回空结果，不抛出异常。

# 启动 Milvus
docker compose -f docker-compose.milvus.yml up -d
# 检查 Milvus 服务
docker compose -f docker-compose.milvus.yml ps
# 停止 Milvus
docker compose -f docker-compose.milvus.yml down

"""

import logging
import socket
import threading
import time
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# 常量定义：与 bge-m3 对齐
default_dim = 1024


def _lazy_import_pymilvus():
    """延迟导入 pymilvus，未安装时返回 None。"""
    try:
        import pymilvus
        return pymilvus
    except ImportError:
        return None


class MilvusClient:
    """Milvus 客户端封装。

    Attributes:
        host: Milvus 服务地址。
        port: Milvus gRPC 端口。
        collection_name: 集合名称。
        dim: 稠密向量维度，默认 1024。
    """

    DIM = 1024
    MAX_CONTENT_LEN = 8192
    MAX_SOURCE_LEN = 256
    MAX_CITY_LEN = 64
    MAX_CATEGORY_LEN = 64

    def __init__(self, host: str, port: str, collection_name: str, dim: int = DIM):
        self.host = host
        self.port = str(port)
        self.collection_name = collection_name
        self.dim = dim
        self._pymilvus = _lazy_import_pymilvus()
        self._collection = None
        self._available = False
        self._ensure_collection()

    # ------------------------------------------------------------------
    # 集合管理
    # ------------------------------------------------------------------
    @staticmethod
    def _is_port_open(host: str, port: str, timeout: float = 2.0) -> bool:
        """快速检测目标端口是否可达，避免 PyMilvus 长时间阻塞。"""
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            return False

    def _ensure_collection(self) -> bool:
        """连接 Milvus 并确保集合存在。

        整个连接与 collection.load() 过程用线程池包裹超时，
        避免 Milvus 服务未就绪时阻塞 Streamlit 启动。
        """
        if self._pymilvus is None:
            logger.warning("[RAG] pymilvus 未安装，Milvus 客户端不可用")
            return False

        if not self._is_port_open(self.host, self.port):
            logger.warning(
                "[RAG] Milvus 端口不可达 %s:%s，RAG 客户端将不可用",
                self.host, self.port,
            )
            return False

        result = {"value": False}

        def _connect_and_load():
            try:
                self._pymilvus.connections.connect(
                    alias="default",
                    host=self.host,
                    port=self.port,
                )
                if self._pymilvus.utility.has_collection(self.collection_name):
                    collection = self._pymilvus.Collection(self.collection_name)
                else:
                    collection = self._create_collection()
                collection.load()
                self._collection = collection
                self._available = True
                result["value"] = True
            except Exception as e:  # noqa: BLE001
                logger.warning("[RAG] Milvus 集合初始化失败: %s", e)
                result["value"] = False

        t = threading.Thread(target=_connect_and_load, daemon=True)
        t.start()
        t.join(timeout=10.0)

        if t.is_alive():
            logger.warning(
                "[RAG] Milvus 连接/加载集合超时 %s:%s，RAG 客户端将不可用",
                self.host, self.port,
            )
            return False
        return result["value"]

    def _create_collection(self):
        """创建旅游知识库 Collection。"""
        pymilvus = self._pymilvus
        fields = [
            pymilvus.FieldSchema(
                name="id", dtype=pymilvus.DataType.VARCHAR,
                max_length=64, is_primary=True,
            ),
            pymilvus.FieldSchema(
                name="doc_id", dtype=pymilvus.DataType.VARCHAR, max_length=64,
            ),
            pymilvus.FieldSchema(
                name="chunk_idx", dtype=pymilvus.DataType.INT32,
            ),
            pymilvus.FieldSchema(
                name="content", dtype=pymilvus.DataType.VARCHAR,
                max_length=self.MAX_CONTENT_LEN,
            ),
            pymilvus.FieldSchema(
                name="embedding", dtype=pymilvus.DataType.FLOAT_VECTOR, dim=self.dim,
            ),
            pymilvus.FieldSchema(
                name="sparse_embedding", dtype=pymilvus.DataType.SPARSE_FLOAT_VECTOR,
            ),
            pymilvus.FieldSchema(
                name="source", dtype=pymilvus.DataType.VARCHAR,
                max_length=self.MAX_SOURCE_LEN,
            ),
            pymilvus.FieldSchema(
                name="page", dtype=pymilvus.DataType.INT32,
            ),
            pymilvus.FieldSchema(
                name="city", dtype=pymilvus.DataType.VARCHAR,
                max_length=self.MAX_CITY_LEN,
            ),
            pymilvus.FieldSchema(
                name="category", dtype=pymilvus.DataType.VARCHAR,
                max_length=self.MAX_CATEGORY_LEN,
            ),
        ]
        schema = pymilvus.CollectionSchema(
            fields, description="旅游知识库向量集合", enable_dynamic_field=True,
        )
        collection = pymilvus.Collection(self.collection_name, schema)

        # 稠密向量索引（HNSW，COSINE）
        dense_index = {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        }
        collection.create_index(field_name="embedding", index_params=dense_index)

        # 稀疏向量索引（BM25 / IP）
        sparse_index = {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "IP",
        }
        collection.create_index(field_name="sparse_embedding", index_params=sparse_index)
        return collection

    # ------------------------------------------------------------------
    # 数据写入 / 删除
    # ------------------------------------------------------------------
    def insert(self, entities: List[Dict[str, Any]]) -> bool:
        """批量插入文档片段。"""
        if not self._available or not self._collection:
            return False
        if not entities:
            return True

        try:
            # 用当前 batch 的 contents 统一 fit BM25，确保稀疏向量维度一致
            contents = [e.get("content", "") for e in entities]
            sparse_vectors = self._batch_bm25_encode(contents)
            for entity, sparse_vec in zip(entities, sparse_vectors):
                entity["sparse_embedding"] = sparse_vec

            rows = [self._entity_to_row(e) for e in entities]
            self._collection.insert(rows)
            self._collection.flush()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Milvus 插入失败: %s", e)
            return False

    def delete(self, expr: str) -> bool:
        """按表达式删除数据。"""
        if not self._available or not self._collection:
            return False
        try:
            self._collection.delete(expr)
            self._collection.flush()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Milvus 删除失败: %s", e)
            return False

    def get_by_ids(self, ids: List[str]) -> List[Dict[str, Any]]:
        """按主键 id 批量查询完整记录。"""
        if not self._available or not self._collection or not ids:
            return []
        try:
            res = self._collection.query(
                expr=f'id in [{", ".join(repr(i) for i in ids)}]',
                output_fields=[
                    "id", "doc_id", "chunk_idx", "content", "source",
                    "page", "city", "category",
                ],
            )
            return [dict(r) for r in res]
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Milvus query 失败: %s", e)
            return []

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(
        self,
        vectors: List[List[float]],
        top_k: int,
        metric_type: str = "COSINE",
        expr: str = "",
    ) -> List[List[Dict[str, Any]]]:
        """稠密向量相似度检索。

        Returns:
            外层为每个查询向量，内层为该查询的 top-k 结果字典列表。
        """
        if not self._available or not self._collection or not vectors:
            return []
        try:
            search_params = {"metric_type": metric_type, "params": {"ef": 64}}
            results = self._collection.search(
                data=vectors,
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=["id"],
            )
            return [
                [{"id": hit.id, "distance": hit.distance} for hit in r]
                for r in results
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Milvus search 失败: %s", e)
            return []

    def hybrid_search(
        self,
        dense_vectors: List[List[float]],
        sparse_vectors: List,
        top_k: int,
        expr: str = "",
    ) -> List[List[Dict[str, Any]]]:
        """混合检索（Dense + Sparse）。

        Args:
            dense_vectors: 稠密向量列表。
            sparse_vectors: 与 dense_vectors 对应的稀疏向量列表。
            top_k: 每查询返回数量。
            expr: 过滤表达式。

        Returns:
            检索结果，格式同 ``search``。
        """
        if not self._available or not self._collection:
            return []
        try:
            pymilvus = self._pymilvus
            dense_req = pymilvus.AnnSearchRequest(
                data=dense_vectors,
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"ef": 64}},
                limit=top_k,
                expr=expr,
            )
            sparse_req = pymilvus.AnnSearchRequest(
                data=sparse_vectors,
                anns_field="sparse_embedding",
                param={"metric_type": "IP", "params": {}},
                limit=top_k,
                expr=expr,
            )
            # 兼容不同 PyMilvus 版本：2.6.16+ 提供 WeightedRanker，旧版回退到 RRF
            if hasattr(pymilvus, "WeightedRanker"):
                rerank = pymilvus.WeightedRanker(0.7, 0.3)
            elif hasattr(pymilvus, "RRFRanker"):
                rerank = pymilvus.RRFRanker()
            else:
                logger.warning(
                    "[RAG] PyMilvus 无内置 Ranker，hybrid_search 退化为 dense_search"
                )
                return self.search(dense_vectors, top_k, metric_type="COSINE", expr=expr)

            results = self._collection.hybrid_search(
                reqs=[dense_req, sparse_req],
                rerank=rerank,
                limit=top_k,
            )
            return [
                [{"id": hit.id, "distance": hit.distance} for hit in r]
                for r in results
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Milvus hybrid_search 失败: %s", e)
            return []

    def text_search(self, query_text: str, top_k: int) -> List[Dict[str, Any]]:
        """全文检索（BM25）。

        使用 pymilvus.model 的 BM25EmbeddingFunction 将查询文本编码为
        稀疏向量后检索 sparse_embedding 字段。
        """
        if not self._available or not self._collection or not query_text:
            return []
        try:
            sparse_vec = self._bm25_encode([query_text])
            if not sparse_vec:
                return []
            results = self._collection.search(
                data=sparse_vec,
                anns_field="sparse_embedding",
                param={"metric_type": "IP", "params": {}},
                limit=top_k,
                output_fields=["id"],
            )
            if not results:
                return []
            return [{"id": hit.id, "distance": hit.distance} for hit in results[0]]
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] Milvus text_search 失败: %s", e)
            return []

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _entity_to_row(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """将业务实体转换为 Milvus 行格式。"""
        content = entity.get("content", "")
        if len(content) > self.MAX_CONTENT_LEN:
            content = content[: self.MAX_CONTENT_LEN]
        return {
            "id": entity.get("id", ""),
            "doc_id": entity.get("doc_id", ""),
            "chunk_idx": int(entity.get("chunk_idx", 0)),
            "content": content,
            "embedding": entity.get("embedding", []),
            "sparse_embedding": entity.get("sparse_embedding") or {0: 0.0},
            "source": entity.get("source", "")[: self.MAX_SOURCE_LEN],
            "page": int(entity.get("page", 0) or 0),
            "city": (entity.get("city", "") or "")[: self.MAX_CITY_LEN],
            "category": (entity.get("category", "") or "")[: self.MAX_CATEGORY_LEN],
        }

    def _batch_bm25_encode(self, texts: List[str]) -> List[Dict[int, float]]:
        """将一批文本编码为 Milvus 可接受的稀疏向量 dict（BM25）。

        用当前 batch 作为 corpus fit，保证维度一致。
        """
        if not texts:
            return []
        try:
            from pymilvus.model.sparse import BM25EmbeddingFunction
            from pymilvus.model.sparse.bm25.tokenizers import build_default_analyzer

            analyzer = build_default_analyzer(language="zh")
            bm25_ef = BM25EmbeddingFunction(analyzer)
            bm25_ef.fit(texts)
            encoded = bm25_ef.encode_documents(texts)

            result = []
            for i in range(encoded.shape[0]):
                row = encoded[i]
                arr = row.toarray().flatten()
                vec = {int(idx): float(val) for idx, val in enumerate(arr) if val != 0}
                # Milvus 不允许全零/空稀疏向量，fallback 到占位值
                result.append(vec if vec else {0: 0.0})
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] BM25 批量编码失败: %s", e)
            return [{0: 0.0} for _ in texts]

    def _bm25_encode(self, texts: List[str]) -> List[Dict[int, float]]:
        """将文本编码为稀疏向量（BM25），主要用于查询。"""
        if not texts:
            return []
        # 查询没有 corpus，使用 batch 接口直接 fit 自身作为近似 corpus
        return self._batch_bm25_encode(texts)
