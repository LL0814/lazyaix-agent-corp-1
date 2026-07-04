"""Skills 模块包入口。

agent.py 会执行 `from skills import Skill`，
因此这里导出 Skill 类作为模块顶层符号。

模块结构：
  skills/
  ├── skill.py                    # 路由主类
  ├── common/                     # 共享代码（槽位提取/校验/格式化/工具函数）
  ├── requirement_alignment/      # Skill 1：需求对齐
  │   ├── SKILL.md
  │   └── scripts/handle.py
  ├── itinerary_planning/         # Skill 2：行程规划
  │   ├── SKILL.md
  │   └── scripts/handle.py
  └── itinerary_validation/       # Skill 3：行程校验
      ├── SKILL.md
      └── scripts/handle.py
"""

from .skill import Skill
from .common.models import UserRequirement

__all__ = ["Skill", "UserRequirement"]
