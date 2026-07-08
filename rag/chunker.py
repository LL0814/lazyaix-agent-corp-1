"""文本分块器：按 Markdown 标题与句子边界切分文档。"""

import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class Chunker:
    """结构感知文本分块器。

    分块策略：
      1. 优先按 Markdown 标题（#、##、###）粗分，保持语义完整性。
      2. 超长段落按句子边界二次切分。
      3. 相邻块之间保留 ``chunk_overlap`` 字符重叠，避免上下文断裂。
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = max(64, chunk_size)
        self.chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))

    def split(self, text: str, metadata: Optional[dict] = None) -> List[Dict]:
        """将文本切分为块。

        Args:
            text: 原始文本内容。
            metadata: 全局元数据，会合并到每个 chunk 的 metadata 中。

        Returns:
            [
                {"content": "...", "chunk_idx": 0, "metadata": {...}},
                ...
            ]
        """
        if not text:
            return []

        sections = self._split_by_headers(text)
        chunks: List[str] = []
        for section in sections:
            section = section.strip()
            if not section:
                continue
            if len(section) <= self.chunk_size:
                chunks.append(section)
            else:
                sub_chunks = self._split_by_sentences(section)
                chunks.extend(sub_chunks)

        base_metadata = metadata or {}
        result = []
        for i, content in enumerate(chunks):
            chunk_metadata = dict(base_metadata)
            result.append({
                "content": content,
                "chunk_idx": i,
                "metadata": chunk_metadata,
            })
        return result

    def _split_by_headers(self, text: str) -> List[str]:
        """按 Markdown 标题（H1/H2/H3）切分文本。"""
        # 匹配行首的 #、##、### 标题
        pattern = re.compile(r"^(#{1,3})\s+", re.MULTILINE)
        matches = list(pattern.finditer(text))
        if not matches:
            return [text]

        sections = []
        start = 0
        for match in matches:
            if match.start() > start:
                sections.append(text[start:match.start()])
            start = match.start()
        sections.append(text[start:])
        return [s.strip() for s in sections if s.strip()]

    def _split_by_sentences(self, text: str) -> List[str]:
        """按句子边界切分超长段落，控制每块长度并保留重叠。"""
        # 简单句子切分：以。！？.!? 结尾，标点后可无空格（中文常见）
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            # 回退：按字符硬切
            return self._split_fixed(text)

        chunks = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= self.chunk_size:
                current = f"{current}\n{sentence}".strip() if current else sentence
            else:
                if current:
                    chunks.append(current)
                # 保留重叠
                if self.chunk_overlap > 0 and current:
                    overlap_text = current[-self.chunk_overlap:]
                    current = overlap_text + sentence
                    if len(current) > self.chunk_size:
                        current = current[-self.chunk_size:]
                else:
                    current = sentence
        if current:
            chunks.append(current)
        return chunks

    def _split_fixed(self, text: str) -> List[str]:
        """按固定长度切分（最后兜底策略）。"""
        chunks = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunks.append(text[start:end].strip())
            start += step
        return [c for c in chunks if c]
