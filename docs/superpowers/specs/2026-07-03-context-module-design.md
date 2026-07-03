# 旅游助手 Agent — Context 模块设计文档

> **文档版本**：v1.0
> **编写日期**：2026-07-03
> **负责人**：Context 模块开发
> **项目性质**：练手项目

---

## 一、文档说明

本文档定义旅游助手 Agent 中 **Context 模块** 的规格与实现约定。

### 1.1 分层定义

- **Context 模块（短期记忆）**：维护当前会话的实时状态，供 `Skill` 做单步决策时使用。
- 它不处理业务理解（槽位提取由 `Skill` 负责），也不做跨会话持久化（持久化由 `Memory` 负责）。

### 1.2 设计目标

1. **功能完整**：同时维护最近 N 轮对话、结构化旅行需求槽位、当前已生成行程。
2. **接口兼容**：保留项目 README 中约定的 `update(input)` / `get()` 接口。
3. **边界清晰**：只做状态容器，不调用 LLM，不调用外部 API。
4. **易于测试**：纯内存操作，无文件 IO 和网络依赖。

### 1.3 接口契约

| 模块 | 类名 | 核心方法 |
|------|------|----------|
| context | `Context` | `update(user_input)` / `add_turn(role, content)` / `set_slots(slots)` / `set_itinerary(itinerary)` / `reset()` / `get()` |

---

## 二、环境变量配置

| 变量名 | 说明 | 示例值 | 是否必需 |
|--------|------|--------|----------|
| `CONTEXT_MAX_HISTORY` | 保留的最大对话轮数 | `10` | 否，默认 10 |

> 该变量仅控制 `Context` 内部 `turns` 列表长度，`Memory` 的历史保存策略不受影响。

---

## 三、架构设计

### 3.1 模块定位

```text
用户输入
    ↓
Agent.process_turn()
    ├─→ Context.update(user_input)        # 记录 user 轮次
    ├─→ Model.complete(prompt)
    ├─→ Skill.decide(..., context.get(), memory)
    │       ├─→ Skill 可调用 context.set_slots(slots)
    │       └─→ Agent 可调用 context.set_itinerary(result)
    ├─→ Tool.execute()（如需要）
    └─→ Context.add_turn("assistant", result)  # 记录 assistant 轮次
```

- `Agent` 负责把 user / assistant 的输入写进 `Context`。
- `Skill` 负责读取 `context.get()` 做决策，并写回 `slots` / `itinerary`。
- `Memory` 继续保存历史 Q&A，与 `Context` 解耦。

### 3.2 类职责

| 类 | 职责 |
|----|------|
| `Context` | 维护会话状态，提供增删改查接口，控制历史长度。 |

---

## 四、数据模型

`Context` 内部用一个 dict 保存状态：

```python
{
    "turn_count": int,              # 当前轮次计数，从 0 开始
    "turns": [                      # 最近 N 轮对话，N = CONTEXT_MAX_HISTORY
        {"role": "user", "content": "...", "timestamp": "..."},
        {"role": "assistant", "content": "...", "timestamp": "..."},
    ],
    "slots": {                      # 结构化旅行需求，由 Skill 维护
        "destination": "成都",      # 目的地
        "days": 3,                  # 天数
        "budget": "mid",            # low / mid / high
        "preferences": "..."        # 其他偏好
    },
    "itinerary": Any | None,        # 当前已生成行程，可为 dict / dataclass
}
```

### 4.1 `turns` 管理

- 每添加一轮，`turn_count` 自增。
- 当 `turns` 长度超过 `max_history` 时，移除最旧的一条记录。
- `timestamp` 使用 ISO 8601 字符串（本地时间）。

### 4.2 `slots` 合并策略

- `set_slots(slots)` 只覆盖输入中**非 None** 的字段。
- 不会清空已有字段，支持多轮累计填充。

### 4.3 `itinerary`

- 由 `Agent` 在调用 `generate_itinerary` 工具后写回。
- `Context` 只负责存储，不解析内部结构。

---

## 五、接口设计

### 5.1 文件结构

```text
context/
├── __init__.py          # 对外暴露 Context 类
└── context.py           # Context 实现
```

### 5.2 核心代码 Schema

```python
# context/__init__.py
from .context import Context

__all__ = ["Context"]
```

```python
# context/context.py
import os
from copy import deepcopy
from datetime import datetime


class Context:
    """维护当前会话的上下文状态。"""

    DEFAULT_MAX_HISTORY = 10

    def __init__(self, config=None):
        self._max_history = self._resolve_max_history(config)
        self._state = {
            "turn_count": 0,
            "turns": [],
            "slots": {},
            "itinerary": None,
        }

    @staticmethod
    def _resolve_max_history(config):
        if config is not None:
            return int(config.get("CONTEXT_MAX_HISTORY", Context.DEFAULT_MAX_HISTORY))
        return int(os.environ.get("CONTEXT_MAX_HISTORY", Context.DEFAULT_MAX_HISTORY))

    def update(self, user_input: str) -> dict:
        """兼容旧接口：添加一轮 user 输入。"""
        return self.add_turn("user", user_input)

    def add_turn(self, role: str, content: str) -> dict:
        """添加 user / assistant 任意一轮。"""
        if role not in ("user", "assistant"):
            raise ValueError(f"role 必须是 'user' 或 'assistant'，当前: {role!r}")
        self._state["turn_count"] += 1
        self._state["turns"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        self._state["turns"] = self._state["turns"][-self._max_history:]
        return self.get()

    def set_slots(self, slots: dict) -> dict:
        """合并新的槽位到 slots。"""
        if not isinstance(slots, dict):
            raise TypeError("slots 必须是 dict")
        for key, value in slots.items():
            if value is not None:
                self._state["slots"][key] = value
        return self.get()

    def get_slots(self) -> dict:
        return deepcopy(self._state["slots"])

    def set_itinerary(self, itinerary) -> dict:
        self._state["itinerary"] = itinerary
        return self.get()

    def get_itinerary(self):
        return deepcopy(self._state["itinerary"])

    def reset(self) -> dict:
        self._state = {
            "turn_count": 0,
            "turns": [],
            "slots": {},
            "itinerary": None,
        }
        return self.get()

    def get(self) -> dict:
        """返回当前上下文的深拷贝，防止外部直接修改内部状态。"""
        return deepcopy(self._state)
```

---

## 六、与现有代码的集成

### 6.1 `agent.py` 改动

`Agent.process_turn()` 中：

1. 保留 `self.context.update(user_input)` 记录 user 输入。
2. 在返回结果前新增 `self.context.add_turn("assistant", result)` 记录 assistant 回复。

`Skill` 可在 `decide(...)` 中通过 `context.set_slots(...)` 更新需求槽位；`Agent` 可在工具执行后通过 `context.set_itinerary(...)` 保存行程。

### 6.2 `loop.py` / `app.py` 改动

- `loop.py` 中的 `Context` Stub 被真实实现替换，其他逻辑不变。
- `app.py` 中的 `SimpleContext` 可替换为 `context.Context`，接口兼容。

---

## 七、错误处理

| 场景 | 行为 |
|------|------|
| `add_turn` 传入非法 `role` | 抛出 `ValueError` |
| `set_slots` 传入非 dict | 抛出 `TypeError` |
| `set_itinerary` 传入 None | 允许，表示清空当前行程 |
| 外部修改 `get()` 返回值 | 不影响内部状态（深拷贝） |

---

## 八、测试策略

新增 `context/test_context.py`（或项目统一的 `tests/test_context.py`），覆盖：

1. 默认初始化结构正确。
2. `update` 与 `add_turn` 增加轮次并更新 `turn_count`。
3. `turns` 超过 `max_history` 后自动截断。
4. `set_slots` 合并与覆盖行为（None 不覆盖）。
5. `set_itinerary` / `get_itinerary` 保存与读取。
6. `reset` 清空所有状态。
7. `get()` 返回深拷贝，外部修改不影响内部。

---

## 九、扩展项（可选）

| 优先级 | 扩展项 | 说明 |
|--------|--------|------|
| P2 | 持久化后端 | 抽象 `ContextBackend`，默认 `MemoryBackend`，未来可接入 `FileBackend` 或数据库。 |
| P2 | 槽位版本号 | 为 `slots` 增加 `version` 字段，方便 Skill 判断需求是否已变更。 |
| P3 | 上下文摘要 | 长对话时调用 LLM 对旧历史做摘要，进一步降低 prompt 长度。 |

> 当前版本不包含以上扩展，仅在设计上预留接口位置。

---

## 十、变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-07-03 | 初稿：定义 Context 模块数据模型、接口、集成方式与测试策略 |
