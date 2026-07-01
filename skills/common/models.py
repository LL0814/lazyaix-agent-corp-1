"""Skills 共享数据结构。

定义用户需求（UserRequirement），
作为槽位提取与行程规划之间的契约。
"""

from dataclasses import dataclass
from typing import Optional, Literal


@dataclass
class UserRequirement:
    """用户旅需结构化表示（槽位填充结果）。

    由 SlotExtractor 从用户自然语言输入中提取。
    destination / days / budget 三项齐全时视为"需求完整"。
    """
    destination: Optional[str] = None       # 目的地，如 "成都"
    days: Optional[int] = None              # 天数，如 3
    budget: Optional[int] = None            # 预算总额（元），如 3000
    budget_level: Literal["low", "mid", "high"] = "mid"  # 预算级别
    preferences: Optional[str] = None       # 偏好，如 "喜欢自然风光"

    def is_complete(self) -> bool:
        """判断核心槽位是否齐全（destination / days / budget）。"""
        return all([self.destination, self.days, self.budget])

    def missing_slots(self) -> list[str]:
        """返回缺失的槽位名列表，用于生成追问。"""
        missing = []
        if not self.destination:
            missing.append("destination")
        if not self.days:
            missing.append("days")
        if not self.budget:
            missing.append("budget")
        return missing
