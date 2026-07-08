"""RRF（Reciprocal Rank Fusion）融合算法实现。

提供无训练、基于排名的多路检索结果融合能力。
"""

from collections import defaultdict
from typing import List, Tuple


class Fusion:
    """RRF 融合器。

    将多个检索系统返回的 doc_id 排名列表融合为单一排名，
    无需对原始分数做归一化。
    """

    DEFAULT_K = 60

    @staticmethod
    def rrf_fuse(ranked_lists: List[List[str]], k: int = DEFAULT_K) -> List[Tuple[str, float]]:
        """融合多个排名列表。

        Args:
            ranked_lists: 多个检索路返回的 doc_id 排名列表，
                每个列表按相关性降序排列。
            k: RRF 平滑常数，默认 60。

        Returns:
            [(doc_id, rrf_score), ...]，按 rrf_score 降序排列。
            若 ranked_lists 为空，返回空列表。
        """
        if not ranked_lists:
            return []

        scores = defaultdict(float)
        for ranking in ranked_lists:
            for position, doc_id in enumerate(ranking, start=1):
                if not doc_id:
                    continue
                scores[doc_id] += 1.0 / (k + position)

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)
