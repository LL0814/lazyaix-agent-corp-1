"""RAGTool 主类：对外提供统一的检索与文档管理入口。"""

import hashlib
import logging
import os
from typing import List, Dict, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .chunker import Chunker
from .embedder import Embedder
from .fusion import Fusion
from .milvus_client import MilvusClient
from .parser import Parser
from .reranker import Reranker
from .retriever import Retriever

logger = logging.getLogger(__name__)


class RAGTool:
    """旅游知识库 RAG 工具。

    核心能力：
      - ``retrieve``: 多路召回 -> RRF 融合 -> 精排 -> 返回 top-k 文档片段。
      - ``index_document``: 解析 -> 分块 -> 向量化 -> 入库。
      - ``delete_document``: 按 doc_id 删除文档的所有 chunk。

    当 ``RAG_ENABLED`` 为 false 或外部服务不可用时，所有方法均安全降级，
    不抛出异常。
    """

    DEFAULT_CHUNK_SIZE = 512
    DEFAULT_CHUNK_OVERLAP = 50
    DEFAULT_RRF_K = 60
    DEFAULT_RERANK_TOPK = 5
    DEFAULT_RETRIEVAL_TOPK = 20

    def __init__(self):
        self.enabled = os.environ.get("RAG_ENABLED", "false").lower() == "true"
        if not self.enabled:
            self.embedder = None
            self.reranker = None
            self.milvus = None
            self.retriever = None
            self.chunker = None
            self.parser = None
            self.fusion = None
            return

        # Embedding / Reranker 配置：优先读取新的通用环境变量，
        # 未设置时回退到旧的 OLLAMA_* 变量。
        # 模型、base_url 等核心参数必须写在 .env 中，代码里不再硬编码默认值。
        embed_base_url = os.environ.get("EMBED_API_BASE_URL")
        embed_api_key = os.environ.get("EMBED_API_KEY", "")
        embed_model = os.environ.get("EMBED_MODEL")
        embed_dim = os.environ.get("EMBED_DIM")
        rerank_base_url = os.environ.get("RERANK_API_BASE_URL")
        rerank_api_key = os.environ.get("RERANK_API_KEY", "")
        rerank_model = os.environ.get("RERANK_MODEL")

        ollama_host = os.environ.get("OLLAMA_HOST")
        if ollama_host and not embed_base_url:
            embed_base_url = f"{ollama_host.rstrip('/')}/v1"
            if embed_model is None:
                embed_model = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
            if embed_dim is None:
                embed_dim = "1024"
        if ollama_host and not rerank_base_url:
            # Ollama 没有 OpenAI 兼容的 rerank 端点，保持使用 /reranks 路径
            rerank_base_url = ollama_host.rstrip("/")
            if rerank_model is None:
                rerank_model = os.environ.get(
                    "OLLAMA_RERANK_MODEL", "qllama/bge-reranker-v2-m3"
                )

        # 校验必要配置：缺少 Embedding / Rerank 入口时安全降级
        if not embed_base_url or not embed_model:
            logger.error(
                "[RAG] 未配置 Embedding API（EMBED_API_BASE_URL + EMBED_MODEL），"
                "或未设置 OLLAMA_HOST 作为回退，RAG 将禁用"
            )
            self.enabled = False
            self.embedder = None
            self.reranker = None
            self.milvus = None
            self.retriever = None
            self.chunker = None
            self.parser = None
            self.fusion = None
            return
        if not rerank_base_url or not rerank_model:
            logger.error(
                "[RAG] 未配置 Rerank API（RERANK_API_BASE_URL + RERANK_MODEL），"
                "或未设置 OLLAMA_HOST 作为回退，RAG 将禁用"
            )
            self.enabled = False
            self.embedder = None
            self.reranker = None
            self.milvus = None
            self.retriever = None
            self.chunker = None
            self.parser = None
            self.fusion = None
            return

        embed_dim = int(embed_dim or "1024")

        milvus_host = os.environ.get("MILVUS_HOST", "localhost")
        milvus_port = os.environ.get("MILVUS_PORT", "19530")
        collection_name = os.environ.get("MILVUS_COLLECTION", "travel_kb")
        mineru_config_path = os.environ.get("MINERU_CONFIG_PATH")

        self.chunk_size = int(
            os.environ.get("RAG_CHUNK_SIZE", self.DEFAULT_CHUNK_SIZE)
        )
        self.chunk_overlap = int(
            os.environ.get("RAG_CHUNK_OVERLAP", self.DEFAULT_CHUNK_OVERLAP)
        )
        self.rrf_k = int(os.environ.get("RAG_RRF_K", self.DEFAULT_RRF_K))
        self.rerank_topk = int(
            os.environ.get("RAG_RERANK_TOPK", self.DEFAULT_RERANK_TOPK)
        )
        self.retrieval_topk = int(
            os.environ.get("RAG_RETRIEVAL_TOPK", self.DEFAULT_RETRIEVAL_TOPK)
        )

        self.embedder = Embedder(
            base_url=embed_base_url,
            api_key=embed_api_key,
            model=embed_model,
            dim=embed_dim,
        )
        self.reranker = Reranker(
            base_url=rerank_base_url,
            api_key=rerank_api_key,
            model=rerank_model,
        )
        self.milvus = MilvusClient(
            host=milvus_host,
            port=milvus_port,
            collection_name=collection_name,
            dim=self.embedder.dim,
        )
        self.retriever = Retriever(self.milvus, self.embedder)
        self.chunker = Chunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self.parser = Parser(config_path=mineru_config_path)
        self.fusion = Fusion()

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> List[Dict]:
        """检索旅游知识库。

        Args:
            query: 查询文本。
            top_k: 返回结果数量，默认 5。
            filters: 元数据过滤条件，例如 {"city": "成都"}。

        Returns:
            文档片段列表，按相关性降序排列。
        """
        if not self.enabled:
            return []

        logger.info("[RAG] 开始检索: query=%s, top_k=%d, filters=%s", query, top_k, filters)
        try:
            # 1. 多路粗排召回（5 路 x top-20）
            ranked_lists = self.retriever.multi_search(
                query, top_k=self.retrieval_topk, filters=filters,
            )
            logger.info("[RAG] 五路召回完成，各路结果数=%s", [len(r) for r in ranked_lists])

            # 2. RRF 融合（k=60），取 top-20 候选
            fused = self.fusion.rrf_fuse(ranked_lists, k=self.rrf_k)
            candidate_ids = [doc_id for doc_id, _ in fused[: self.retrieval_topk]]
            logger.info("[RAG] RRF 融合后候选数=%d", len(candidate_ids))
            if not candidate_ids:
                return []

            # 3. 获取候选文档内容
            candidates = self.milvus.get_by_ids(candidate_ids)
            logger.info("[RAG] 查询候选文档内容数=%d", len(candidates))
            if not candidates:
                return []

            # 4. 精排重排序
            passages = [c.get("content", "") for c in candidates]
            reranked = self.reranker.rerank(query, passages, top_k=top_k)
            logger.info("[RAG] 精排完成，返回 top-%d", len(reranked))

            # 5. 组装结果
            results = []
            for idx, score in reranked:
                if idx < 0 or idx >= len(candidates):
                    continue
                doc = candidates[idx]
                results.append({
                    "chunk_id": doc.get("id", ""),
                    "content": doc.get("content", ""),
                    "source": doc.get("source", ""),
                    "page": doc.get("page", 0),
                    "score": float(score),
                    "metadata": {
                        "city": doc.get("city", ""),
                        "category": doc.get("category", ""),
                    },
                })
            logger.info("[RAG] 检索完成，返回结果数=%d", len(results))
            return results
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] retrieve 执行异常: %s", e)
            return []

    def index_document(
        self,
        file_path: str,
        metadata: Optional[dict] = None,
    ) -> bool:
        """将文档解析、分块、向量化后入库。

        Args:
            file_path: 文档路径。
            metadata: 文档元数据，例如 {"city": "成都", "category": "攻略"}。

        Returns:
            入库成功返回 True，否则返回 False。
        """
        if not self.enabled:
            return False

        logger.info("[RAG] 开始索引文档: %s, metadata=%s", file_path, metadata)
        try:
            metadata = metadata or {}
            parsed = self.parser.parse(file_path)
            text = parsed.get("markdown", "")
            if not text:
                logger.warning("[RAG] 文档解析结果为空: %s", file_path)
                return False

            doc_id = hashlib.md5(file_path.encode("utf-8")).hexdigest()[:16]

            # 幂等：同名文件再次索引时，先删除旧 chunk 再重新写入
            self.delete_document(doc_id)

            # 合并解析出的元数据
            chunk_metadata = {
                "source": os.path.basename(file_path),
                "page_count": parsed.get("page_count", 0),
            }
            chunk_metadata.update(metadata)

            # 分块
            chunks = self.chunker.split(text, metadata=chunk_metadata)
            if not chunks:
                logger.warning("[RAG] 文档分块结果为空: %s", file_path)
                return False

            # 批量向量化
            contents = [c.get("content", "") for c in chunks]
            vectors = self.embedder.embed_batch(contents)

            # 组装 Milvus 实体
            entities = []
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                if not vec:
                    continue
                chunk_meta = chunk.get("metadata", {})
                entities.append({
                    "id": f"{doc_id}_chunk_{i:03d}",
                    "doc_id": doc_id,
                    "chunk_idx": i,
                    "content": chunk.get("content", ""),
                    "embedding": vec,
                    "source": os.path.basename(file_path),
                    "page": chunk_meta.get("page", 0) or 0,
                    "city": metadata.get("city", ""),
                    "category": metadata.get("category", ""),
                })

            if not entities:
                logger.warning("[RAG] 所有 chunk 向量化失败: %s", file_path)
                return False

            success = self.milvus.insert(entities)
            if success:
                logger.info("[RAG] 文档索引成功: %s, chunks=%d", file_path, len(entities))
                self._mark_indexed(file_path, doc_id)
            else:
                logger.warning("[RAG] 文档索引失败: %s", file_path)
            return success
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] index_document 执行异常: %s", e)
            return False

    def delete_document(self, doc_id: str) -> bool:
        """按 doc_id 删除文档的所有 chunk。

        Args:
            doc_id: 文档 ID。

        Returns:
            删除成功返回 True，否则返回 False。
        """
        if not self.enabled:
            return False
        logger.info("[RAG] 删除文档: doc_id=%s", doc_id)
        try:
            success = self.milvus.delete(f'doc_id == "{doc_id}"')
            logger.info("[RAG] 删除文档结果: %s", success)
            return success
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] delete_document 执行异常: %s", e)
            return False

    def _mark_indexed(self, file_path: str, doc_id: str) -> None:
        """记录文档已索引入库。"""
        try:
            indexed_dir = os.path.join(
                os.path.dirname(__file__), "data", "indexed"
            )
            os.makedirs(indexed_dir, exist_ok=True)
            marker_path = os.path.join(indexed_dir, f"{doc_id}.json")
            import json
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump({
                    "doc_id": doc_id,
                    "file_path": file_path,
                    "source": os.path.basename(file_path),
                }, f, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] 写入索引标记失败: %s", e)
