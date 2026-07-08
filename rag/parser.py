"""文档解析封装。

支持 PDF、Markdown、TXT 等格式，输出结构化文本。
解析优先级：
  1. PyMuPDF (fitz，文本型 PDF 最快)
  2. PaddleOCR（图片型 PDF OCR fallback）
  3. MinerU（复杂版面分析）
  4. PyPDF2
  5. 纯文本/Markdown 直接读取

当所有解析器都不可用时，返回空结果，不抛异常。
"""

import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


class Parser:
    """文档解析器。

    Attributes:
        config_path: MinerU 配置文件路径（可选，目前未使用）。
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self._paddleocr: Optional[object] = None

    def parse(self, file_path: str) -> dict:
        """解析文档，返回结构化结果。

        Args:
            file_path: 文档路径。

        Returns:
            {
                "markdown": "# 标题\\n正文...",
                "json": [...],
                "page_count": 20,
                "metadata": {...}
            }
            当解析失败时，返回 markdown 为空字符串，page_count 为 0。
        """
        if not file_path or not os.path.exists(file_path):
            logger.warning("[RAG] 文件不存在: %s", file_path)
            return self._empty_result()

        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        # 文本/Markdown 直接读取
        if ext in (".env.example.txt", ".md", ".markdown"):
            return self._parse_as_text(file_path)

        # PDF 尝试多种解析器
        # 顺序依据：PyMuPDF 对文本型 PDF 最快；图片型 PDF 无文字层时，
        # PyMuPDF 会快速返回空，接着使用轻量且已缓存的 PaddleOCR。
        if ext == ".pdf":
            parsers = [
                ("PyMuPDF", self._parse_with_pymupdf),
                ("PaddleOCR", self._parse_with_paddleocr),
                ("MinerU", self._parse_with_mineru),
                ("PyPDF2", self._parse_with_pypdf2),
            ]
            for name, parse_func in parsers:
                try:
                    result = parse_func(file_path)
                    if result.get("markdown"):
                        logger.info("[RAG] 使用 %s 解析 PDF: %s", name, file_path)
                        return result
                except Exception as e:  # noqa: BLE001
                    logger.debug("[RAG] %s 解析失败: %s", name, e)
            logger.warning("[RAG] 所有 PDF 解析器均不可用: %s", file_path)
            return self._empty_result()

        logger.warning("[RAG] 不支持的文件类型: %s", ext)
        return self._empty_result()

    def _parse_with_mineru(self, file_path: str) -> dict:
        """使用 MinerU 解析文档，兼容 magic_pdf >= 1.0 的 API。"""
        from magic_pdf.data.data_reader_writer import FileBasedDataReader  # type: ignore
        from magic_pdf.tools.common import do_parse  # type: ignore

        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_dir = os.path.join(
            os.path.dirname(__file__), "data", "parsed", base_name
        )
        os.makedirs(output_dir, exist_ok=True)

        reader = FileBasedDataReader(os.path.dirname(file_path))
        pdf_bytes = reader.read(os.path.basename(file_path))

        # 优先使用 auto，对图片型 PDF 自动降级到 ocr
        last_error: Optional[Exception] = None
        for method in ("auto", "ocr"):
            try:
                do_parse(
                    output_dir,
                    base_name,
                    pdf_bytes,
                    [],
                    method,
                    debug_able=False,
                    f_dump_md=True,
                    f_dump_middle_json=False,
                    f_dump_model_json=False,
                    f_dump_orig_pdf=False,
                    f_dump_content_list=False,
                )
                break
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.debug("[RAG] MinerU %s 模式解析失败: %s", method, e)
        else:
            raise RuntimeError(f"MinerU 解析失败: {last_error}")

        md_path = os.path.join(output_dir, f"{base_name}.md")
        json_path = os.path.join(output_dir, f"{base_name}_middle.json")

        markdown = ""
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as f:
                markdown = f.read()

        parsed_json = []
        if os.path.exists(json_path):
            import json
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    parsed_json = json.load(f)
            except json.JSONDecodeError:
                pass

        return {
            "markdown": markdown,
            "json": parsed_json,
            "page_count": self._estimate_page_count(parsed_json),
            "metadata": {"source": os.path.basename(file_path)},
        }

    def _parse_with_pymupdf(self, file_path: str) -> dict:
        """使用 PyMuPDF (fitz) 解析 PDF。"""
        import fitz  # type: ignore

        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(text)
        doc.close()

        markdown = "\n\n".join(pages)
        return {
            "markdown": markdown,
            "json": [],
            "page_count": len(pages),
            "metadata": {"source": os.path.basename(file_path)},
        }

    def _parse_with_paddleocr(self, file_path: str) -> dict:
        """使用 PaddleOCR 对图片型 PDF 进行 OCR 解析。"""
        import fitz  # type: ignore

        ocr = self._get_paddleocr()
        if ocr is None:
            raise RuntimeError("PaddleOCR 不可用")

        doc = fitz.open(file_path)
        if not doc.page_count:
            doc.close()
            return self._empty_result()

        pages = []
        # 1.0 倍分辨率优先保证速度；对普通阅读型 PDF 文字足够清晰
        matrix = fitz.Matrix(1.0, 1.0)
        logger.info(
            "[RAG] PaddleOCR 开始解析 %d 页，CPU 推理较慢请耐心等待...",
            doc.page_count,
        )
        for page_idx, page in enumerate(doc, start=1):
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False
            ) as tmp_img:
                tmp_path = tmp_img.name
            try:
                pix = page.get_pixmap(matrix=matrix)
                pix.save(tmp_path)
                result = ocr.predict(tmp_path)
                texts = []
                if result and isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict):
                            rec_texts = item.get("rec_texts") or []
                            texts.extend([str(t) for t in rec_texts])
                if texts:
                    pages.append("\n".join(texts))
                logger.info(
                    "[RAG] PaddleOCR 解析第 %d/%d 页完成，识别 %d 行文本",
                    page_idx, doc.page_count, len(texts),
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        doc.close()

        markdown = "\n\n".join(pages)
        return {
            "markdown": markdown,
            "json": [],
            "page_count": len(pages),
            "metadata": {"source": os.path.basename(file_path)},
        }

    def _get_paddleocr(self) -> Optional[object]:
        """延迟初始化并缓存 PaddleOCR 实例。"""
        if self._paddleocr is not None:
            return self._paddleocr
        try:
            # 禁用模型源检查，避免首次使用时的网络探测
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR  # type: ignore

            # 禁用文档预处理以加速；图片型 PDF 通常不需要去畸变和方向分类
            self._paddleocr = PaddleOCR(
                lang="ch",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            return self._paddleocr
        except Exception as e:  # noqa: BLE001
            logger.debug("[RAG] PaddleOCR 初始化失败: %s", e)
            return None

    def _parse_with_pypdf2(self, file_path: str) -> dict:
        """使用 PyPDF2 解析 PDF。"""
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)

        markdown = "\n\n".join(pages)
        return {
            "markdown": markdown,
            "json": [],
            "page_count": len(pages),
            "metadata": {"source": os.path.basename(file_path)},
        }

    def _parse_as_text(self, file_path: str) -> dict:
        """作为纯文本/Markdown 读取。"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:  # noqa: BLE001
            logger.warning("[RAG] 文本读取失败: %s", e)
            return self._empty_result()

        return {
            "markdown": content,
            "json": [],
            "page_count": 1,
            "metadata": {"source": os.path.basename(file_path)},
        }

    def _empty_result(self) -> dict:
        return {
            "markdown": "",
            "json": [],
            "page_count": 0,
            "metadata": {},
        }

    @staticmethod
    def _estimate_page_count(parsed_json) -> int:
        """从 MinerU JSON 输出中估算页数。"""
        if isinstance(parsed_json, dict):
            pages = parsed_json.get("page_info") or parsed_json.get("pages") or []
            return len(pages)
        if isinstance(parsed_json, list):
            return len(parsed_json)
        return 0
