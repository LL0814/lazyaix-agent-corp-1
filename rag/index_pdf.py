"""PDF 一键入库脚本。

把 PDF 文档解析、分块、向量化后写入 Milvus 向量库。

用法：
    python3 scripts/index_pdf.py <pdf_path> [--city 成都] [--category 攻略]

示例：
    python3 scripts/index_pdf.py rag/data/pdfs/成都旅游攻略.pdf --city 成都 --category 攻略
"""

import argparse
import os
import sys

# 兼容直接从 scripts/ 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging import setup_logging

setup_logging()

from rag import RAGTool


def process_pdf(file_path: str, metadata: dict | None = None) -> bool:
    """把单个 PDF/文本文件入库。

    Args:
        file_path: PDF 或 Markdown/TXT 文件路径。
        metadata: 文档元数据，例如 {"city": "成都", "category": "攻略"}。

    Returns:
        入库成功返回 True，失败返回 False。
    """
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False

    rag = RAGTool()
    if not rag.enabled:
        print("❌ RAG 未启用，请检查 .env 中的 RAG_ENABLED=true")
        return False

    print(f"📄 正在处理: {file_path}")
    print(f"🏷️  元数据: {metadata or {}}")

    success = rag.index_document(file_path=file_path, metadata=metadata or {})

    if success:
        print(f"✅ 入库成功: {file_path}")
    else:
        print(f"❌ 入库失败: {file_path}")
        print("   可能原因：Embedding/Rerank API 不可用 / Milvus 未启动 / MinerU 未安装 / 文档解析为空")
    return success


def main():
    parser = argparse.ArgumentParser(description="PDF 一键入库到 RAG 向量库")
    parser.add_argument("file_path", help="PDF 或文本文件路径")
    parser.add_argument("--city", default="", help="文档所属城市（可选）")
    parser.add_argument("--category", default="", help="文档分类（可选）")
    args = parser.parse_args()

    metadata = {}
    if args.city:
        metadata["city"] = args.city
    if args.category:
        metadata["category"] = args.category

    success = process_pdf(args.file_path, metadata=metadata)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
