"""RAG 模块包入口。

对外暴露 ``RAGTool`` 主类，提供旅游知识库的检索与文档管理能力。

本模块依赖的外部服务（仅在 ``RAG_ENABLED=true`` 时初始化）：
  - Embedding API：默认使用阿里云百炼（DashScope）通义 Embedding
  - Rerank API：默认使用阿里云百炼（DashScope）通义 Rerank
  - Milvus：向量数据库存储与检索
  - MinerU：PDF 等复杂文档解析

当外部服务不可用时，所有方法均会优雅降级并返回空结果，不中断 Agent 主流程。
"""

from .tool import RAGTool

__all__ = ["RAGTool"]
