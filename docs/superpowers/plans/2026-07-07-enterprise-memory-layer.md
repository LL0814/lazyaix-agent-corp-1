# 企业级 Memory 层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. 本计划强制逐阶段执行，每个阶段完成后必须写中文阶段报告、提交代码、等待用户确认，不能连续执行多个阶段。

**Goal:** 只实现 `memory/` 层，把当前内存 stub 升级为本地企业级记忆系统，同时保持现有 `Memory.store(key, value)` / `Memory.retrieve(key)` 完全兼容。

**Architecture:** 采用 Path A：SQLite 作为本地权威元数据与兼容 KV 存储，Qdrant 作为语义向量索引，BGE-M3 作为本地 embedding provider。接口按企业分布式形态设计，后续可替换为 Postgres、Kafka/Redpanda、Redis、Qdrant cluster、独立 embedding service，但第一版不引入这些运行时依赖。

**Tech Stack:** Python 3.10+、Pydantic v2、SQLite 标准库、pytest、Qdrant、`qdrant-client`、BGE-M3、`FlagEmbedding`。

## Global Constraints

- 后续所有 Markdown 文档、阶段报告、人工验证说明、交付总结必须使用中文。
- 代码标识符、命令名、文件路径、环境变量名、公开 API 名称保留英文。
- 只实现 `memory/` 层，不修改 `agent.py`、`context/`、`skills/` 的行为，除非某个阶段报告后获得用户明确批准。
- 现有 `Memory.store(key, value)` 和 `Memory.retrieve(key)` 是稳定兼容接口，不能破坏。
- 现有业务 key 必须兼容：`history`、`current_requirement`、`current_itinerary`、`reset_flag`。
- Qdrant collection 默认名为 `agent_memories_v1`。
- BGE-M3 dense vector 维度为 `1024`，Qdrant distance 为 `Cosine`。
- 默认 scope 为 `project`，默认 `tenant_id=local`、`user_id=default`、`project_id=lazyaiX-agent-corp-1`。
- 语义记忆必须支持审计、来源证据、删除/tombstone、导入导出、项目隔离。
- 每个阶段必须先写测试，再实现，最后写中文阶段报告。
- 每个阶段必须单独 commit。
- 每个阶段完成后停止，等待用户确认后才能进入下一阶段。
- 本仓库依赖由 `uv` 管理，测试命令使用 `uv run pytest`，Python 人工验证命令使用 `uv run python`。

---

## 文件结构总览

计划最终创建或修改以下文件：

| 文件 | 职责 |
| --- | --- |
| `memory/__init__.py` | 导出真实 `Memory` 类 |
| `memory/config.py` | 读取环境变量和调用方覆盖配置 |
| `memory/models.py` | 定义 Pydantic 数据模型、枚举和返回类型 |
| `memory/service.py` | Memory facade，承载兼容接口和企业接口 |
| `memory/audit.py` | 审计事件构造和动作名常量 |
| `memory/redaction.py` | 敏感信息脱敏 |
| `memory/classifier.py` | 规则型记忆候选分类 |
| `memory/embeddings.py` | Embedding provider 抽象、BGE-M3 实现、Fake provider |
| `memory/retrieval.py` | 搜索结果重排、过滤、格式化 |
| `memory/exporter.py` | Markdown/JSONL 导入导出 |
| `memory/backends/__init__.py` | 后端包入口 |
| `memory/backends/sqlite_store.py` | SQLite schema、KV、records、sources、outbox、audit、summary |
| `memory/backends/qdrant_store.py` | Qdrant collection、upsert、search、delete |
| `tests/test_memory_interface.py` | 第 1 阶段接口和配置测试 |
| `tests/test_memory_sqlite_store.py` | 第 2 阶段 SQLite 兼容持久化测试 |
| `tests/test_memory_audit_outbox.py` | 第 3 阶段审计和 outbox 测试 |
| `tests/test_memory_redaction_classifier.py` | 第 4 阶段脱敏和分类测试 |
| `tests/test_memory_embeddings.py` | 第 5 阶段 embedding provider 测试 |
| `tests/test_memory_qdrant_store.py` | 第 6 阶段 Qdrant 后端测试 |
| `tests/test_memory_service_semantic.py` | 第 7 阶段 remember/search/forget 测试 |
| `tests/test_memory_import_export_summary.py` | 第 8 阶段 summary/import/export 测试 |
| `tests/test_memory_integration_with_agent_contract.py` | 第 9 阶段现有 Agent 契约集成测试 |
| `pyproject.toml` | 第 5/6 阶段声明可选运行依赖 |
| `.gitignore` | 忽略 `.memory/` 本地数据库 |
| `docs/superpowers/reports/2026-07-07-memory-phase-01.md` | 第 1 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-02.md` | 第 2 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-03.md` | 第 3 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-04.md` | 第 4 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-05.md` | 第 5 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-06.md` | 第 6 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-07.md` | 第 7 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-08.md` | 第 8 阶段中文报告 |
| `docs/superpowers/reports/2026-07-07-memory-phase-09.md` | 第 9 阶段中文报告 |

---

## 执行规则

每个阶段执行时必须遵守：

1. 只执行当前阶段。
2. 先写或更新测试。
3. 跑目标测试，确认失败原因符合预期。
4. 写最小实现。
5. 跑目标测试，确认通过。
6. 根据阶段风险跑更大范围测试。
7. 写中文阶段报告。
8. commit 当前阶段代码和报告。
9. 在聊天里用中文总结本阶段，并请求用户确认是否进入下一阶段。

每份阶段报告必须使用这个结构：

```markdown
# 第 N 阶段报告：阶段名称

## 本阶段目标

## 本阶段改动

## 新增文件

## 修改文件

## 公开接口

## 自动验证

命令：

结果：

## 人工验证

步骤：

预期：

## 已知限制

## 请求确认

请审阅本阶段结果，并确认是否进入第 N+1 阶段。
```

---

## Task 1: 配置和公开接口骨架

**Files:**

- Create: `memory/__init__.py`
- Create: `memory/config.py`
- Create: `memory/models.py`
- Create: `memory/service.py`
- Create: `tests/test_memory_interface.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-01.md`

**Interfaces:**

- Produces: `memory.Memory`
- Produces: `Memory.store(key: str, value: object) -> None`
- Produces: `Memory.retrieve(key: str) -> object | None`
- Produces: `MemoryConfig.from_env(overrides: dict | None = None) -> MemoryConfig`
- Produces: `MemoryScope`, `MemoryKind`, `MemoryStatus`, `MemorySearchResult`, `DebugCounts`

### 步骤

- [ ] **Step 1: 写接口失败测试**

在 `tests/test_memory_interface.py` 写入：

```python
from memory import Memory
from memory.config import MemoryConfig
from memory.models import MemoryKind, MemoryScope, MemoryStatus


def test_memory_imports_real_class():
    memory = Memory()

    assert hasattr(memory, "store")
    assert hasattr(memory, "retrieve")


def test_store_retrieve_in_memory_before_sqlite_backend():
    memory = Memory(config={"MEMORY_BACKEND": "memory"})

    memory.store("hello", {"world": 1})

    assert memory.retrieve("hello") == {"world": 1}


def test_default_config_values():
    config = MemoryConfig.from_env({})

    assert config.enable_memory is True
    assert config.use_memories is True
    assert config.generate_memories is True
    assert config.tenant_id == "local"
    assert config.user_id == "default"
    assert config.project_id == "lazyaiX-agent-corp-1"
    assert config.db_path == ".memory/memory.sqlite3"
    assert config.qdrant_url == "http://localhost:6333"
    assert config.qdrant_collection == "agent_memories_v1"
    assert config.embedding_model == "BAAI/bge-m3"
    assert config.embedding_dimension == 1024


def test_memory_enums_are_stable():
    assert MemoryScope.PROJECT == "project"
    assert MemoryKind.SEMANTIC == "semantic"
    assert MemoryStatus.ACTIVE == "active"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_interface.py -v
```

Expected:

```text
FAILED tests/test_memory_interface.py::test_memory_imports_real_class
```

失败原因应是无法从 `memory` 导入 `Memory`，或 `MemoryConfig` / models 不存在。

- [ ] **Step 3: 实现接口骨架**

在 `memory/models.py` 定义：

```python
"""Memory layer data models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryScope(StrEnum):
    GLOBAL = "global"
    USER = "user"
    PROJECT = "project"
    THREAD = "thread"


class MemoryKind(StrEnum):
    KV_STATE = "kv_state"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    SUMMARY = "summary"
    TOMBSTONE = "tombstone"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    EXPIRED = "expired"


class SourceRef(BaseModel):
    source_id: str
    source_type: str = "manual"
    source_ref: str = ""
    excerpt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class MemoryRecord(BaseModel):
    memory_id: str
    tenant_id: str
    user_id: str
    project_id: str
    thread_id: str | None = None
    scope: MemoryScope = MemoryScope.PROJECT
    kind: MemoryKind = MemoryKind.SEMANTIC
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: MemoryStatus = MemoryStatus.ACTIVE
    confidence: float = 1.0
    importance: float = 0.5
    sensitivity: str = "normal"
    source_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime | None = None


class MemorySearchResult(BaseModel):
    memory_id: str
    content: str
    kind: MemoryKind
    scope: MemoryScope
    score: float
    source: SourceRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DebugCounts(BaseModel):
    kv: int = 0
    records: int = 0
    sources: int = 0
    outbox: int = 0
    audit: int = 0
    summaries: int = 0
```

在 `memory/config.py` 定义：

```python
"""Configuration for the Memory layer."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class MemoryConfig(BaseModel):
    enable_memory: bool = True
    use_memories: bool = True
    generate_memories: bool = True
    disable_on_external_context: bool = True
    redact_secrets: bool = True
    backend: str = "memory"
    tenant_id: str = "local"
    user_id: str = "default"
    project_id: str = "lazyaiX-agent-corp-1"
    thread_id: str | None = None
    db_path: str = ".memory/memory.sqlite3"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "agent_memories_v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "MemoryConfig":
        overrides = overrides or {}
        data = {
            "enable_memory": _bool(os.getenv("ENABLE_MEMORY"), True),
            "use_memories": _bool(os.getenv("MEMORY_USE_MEMORIES"), True),
            "generate_memories": _bool(os.getenv("MEMORY_GENERATE_MEMORIES"), True),
            "disable_on_external_context": _bool(os.getenv("MEMORY_DISABLE_ON_EXTERNAL_CONTEXT"), True),
            "redact_secrets": _bool(os.getenv("MEMORY_REDACT_SECRETS"), True),
            "backend": os.getenv("MEMORY_BACKEND", "memory"),
            "tenant_id": os.getenv("MEMORY_TENANT_ID", "local"),
            "user_id": os.getenv("MEMORY_USER_ID", "default"),
            "project_id": os.getenv("MEMORY_PROJECT_ID", "lazyaiX-agent-corp-1"),
            "thread_id": os.getenv("MEMORY_THREAD_ID") or None,
            "db_path": os.getenv("MEMORY_DB_PATH", ".memory/memory.sqlite3"),
            "qdrant_url": os.getenv("QDRANT_URL", "http://localhost:6333"),
            "qdrant_collection": os.getenv("QDRANT_COLLECTION", "agent_memories_v1"),
            "embedding_model": os.getenv("MEMORY_EMBEDDING_MODEL", "BAAI/bge-m3"),
            "embedding_dimension": int(os.getenv("MEMORY_EMBEDDING_DIMENSION", "1024")),
        }
        data.update(overrides)
        return cls(**data)
```

在 `memory/service.py` 定义：

```python
"""Memory facade used by the agent."""

from __future__ import annotations

from typing import Any

from memory.config import MemoryConfig
from memory.models import DebugCounts


class Memory:
    """Compatibility-first Memory implementation.

    Phase 1 keeps an in-process dictionary so existing callers can import
    the real class before SQLite is connected in Phase 2.
    """

    def __init__(self, config: dict[str, Any] | MemoryConfig | None = None):
        if isinstance(config, MemoryConfig):
            self.config = config
        else:
            self.config = MemoryConfig.from_env(config)
        self._store: dict[str, Any] = {}

    def store(self, key: str, value: object) -> None:
        self._store[key] = value

    def retrieve(self, key: str) -> object | None:
        return self._store.get(key)

    def debug_counts(self) -> DebugCounts:
        return DebugCounts(kv=len(self._store))
```

在 `memory/__init__.py` 定义：

```python
"""Memory module public entrypoint."""

from memory.service import Memory

__all__ = ["Memory"]
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
pytest tests/test_memory_interface.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 5: 写第 1 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-01.md`

报告必须说明：

- `Memory` 入口在 `memory/__init__.py`
- `Memory` 实现在 `memory/service.py`
- 配置在 `memory/config.py`
- 数据模型在 `memory/models.py`
- 当前阶段还没有接 SQLite、Qdrant、BGE-M3
- 人工验证命令：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
m.store("hello", {"world": 1})
print(m.retrieve("hello"))
PY
```

预期：

```text
{'world': 1}
```

- [ ] **Step 6: 提交第 1 阶段**

Run:

```bash
git add memory/__init__.py memory/config.py memory/models.py memory/service.py tests/test_memory_interface.py docs/superpowers/reports/2026-07-07-memory-phase-01.md
git commit -m "feat(memory): add configuration and public interface"
```

Expected:

```text
[context <commit>] feat(memory): add configuration and public interface
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 2。

---

## Task 2: SQLite 兼容 KV 持久化

**Files:**

- Create: `memory/backends/__init__.py`
- Create: `memory/backends/sqlite_store.py`
- Modify: `memory/config.py`
- Modify: `memory/service.py`
- Create: `tests/test_memory_sqlite_store.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-02.md`

**Interfaces:**

- Consumes: `MemoryConfig`
- Produces: `SQLiteMemoryStore.set_kv(key: str, value: object) -> None`
- Produces: `SQLiteMemoryStore.get_kv(key: str) -> object | None`
- Produces: `SQLiteMemoryStore.counts() -> DebugCounts`
- Modifies: `Memory.store` uses SQLite when `backend == "sqlite"`
- Modifies: default `MemoryConfig.backend` from `"memory"` to `"sqlite"` after tests pass

### 步骤

- [ ] **Step 1: 写 SQLite 失败测试**

在 `tests/test_memory_sqlite_store.py` 写入：

```python
from pathlib import Path

from memory import Memory
from memory.backends.sqlite_store import SQLiteMemoryStore


def test_sqlite_store_round_trips_json_value(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(str(db_path))

    store.set_kv("history", [{"input": "我想去成都", "response": "好的"}])

    assert store.get_kv("history") == [{"input": "我想去成都", "response": "好的"}]


def test_memory_persists_across_instances(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    config = {"MEMORY_BACKEND": "sqlite", "MEMORY_DB_PATH": str(db_path)}

    first = Memory(config=config)
    first.store("current_requirement", {"destination": "成都", "days": 3})

    second = Memory(config=config)

    assert second.retrieve("current_requirement") == {"destination": "成都", "days": 3}


def test_non_json_local_object_round_trip(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(str(db_path))
    value = {"items": {1, 2, 3}}

    store.set_kv("non_json", value)

    assert store.get_kv("non_json") == value


def test_debug_counts_reports_kv_rows(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    memory = Memory(config={"MEMORY_BACKEND": "sqlite", "MEMORY_DB_PATH": str(db_path)})

    memory.store("reset_flag", True)

    assert memory.debug_counts().kv == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_sqlite_store.py -v
```

Expected:

```text
FAILED tests/test_memory_sqlite_store.py::test_sqlite_store_round_trips_json_value
```

失败原因应是 `memory.backends.sqlite_store` 不存在。

- [ ] **Step 3: 实现 SQLite store**

在 `memory/backends/__init__.py` 写入：

```python
"""Memory storage backends."""
```

在 `memory/backends/sqlite_store.py` 实现：

```python
"""SQLite storage for local Memory state."""

from __future__ import annotations

import json
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from memory.models import DebugCounts


class SQLiteMemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_kv (
                    key TEXT PRIMARY KEY,
                    value_json TEXT,
                    value_pickle BLOB,
                    value_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")

    @staticmethod
    def _encode(value: object) -> tuple[str | None, bytes | None, str]:
        try:
            return json.dumps(value, ensure_ascii=False), None, "json"
        except TypeError:
            return None, pickle.dumps(value), "pickle"

    @staticmethod
    def _decode(value_json: str | None, value_pickle: bytes | None, value_type: str) -> object | None:
        if value_type == "json" and value_json is not None:
            return json.loads(value_json)
        if value_type == "pickle" and value_pickle is not None:
            return pickle.loads(value_pickle)
        return None

    def set_kv(self, key: str, value: object) -> None:
        value_json, value_pickle, value_type = self._encode(value)
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_kv (key, value_json, value_pickle, value_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    value_pickle = excluded.value_pickle,
                    value_type = excluded.value_type,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, value_pickle, value_type, now, now),
            )
            conn.commit()

    def get_kv(self, key: str) -> object | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json, value_pickle, value_type FROM memory_kv WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._decode(row["value_json"], row["value_pickle"], row["value_type"])

    def counts(self) -> DebugCounts:
        with self._connect() as conn:
            kv_count = conn.execute("SELECT COUNT(*) FROM memory_kv").fetchone()[0]
        return DebugCounts(kv=kv_count)
```

修改 `memory/config.py`：

```python
backend: str = "sqlite"
```

并把 `from_env` 中默认值改为：

```python
"backend": os.getenv("MEMORY_BACKEND", "sqlite"),
```

修改 `memory/service.py`，当 backend 为 `sqlite` 时使用 `SQLiteMemoryStore`：

```python
from memory.backends.sqlite_store import SQLiteMemoryStore
```

`__init__` 中：

```python
self._store: dict[str, Any] = {}
self._sqlite = SQLiteMemoryStore(self.config.db_path) if self.config.backend == "sqlite" else None
```

`store` 中：

```python
if self._sqlite is not None:
    self._sqlite.set_kv(key, value)
else:
    self._store[key] = value
```

`retrieve` 中：

```python
if self._sqlite is not None:
    return self._sqlite.get_kv(key)
return self._store.get(key)
```

`debug_counts` 中：

```python
if self._sqlite is not None:
    return self._sqlite.counts()
return DebugCounts(kv=len(self._store))
```

- [ ] **Step 4: 运行目标测试**

Run:

```bash
pytest tests/test_memory_sqlite_store.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 5: 运行接口回归测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py -v
```

Expected:

```text
7 passed
```

- [ ] **Step 6: 写第 2 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-02.md`

报告必须包含人工验证命令：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual.sqlite3"})
m.store("history", [{"input": "我想去成都", "response": "好的"}])
print(m.retrieve("history"))
PY

uv run python - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual.sqlite3"})
print(m.retrieve("history"))
PY
```

预期两次都输出：

```text
[{'input': '我想去成都', 'response': '好的'}]
```

- [ ] **Step 7: 提交第 2 阶段**

Run:

```bash
git add memory/config.py memory/service.py memory/backends/__init__.py memory/backends/sqlite_store.py tests/test_memory_sqlite_store.py docs/superpowers/reports/2026-07-07-memory-phase-02.md
git commit -m "feat(memory): persist compatibility state in sqlite"
```

Expected:

```text
[context <commit>] feat(memory): persist compatibility state in sqlite
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 3。

---

## Task 3: 审计日志和 Outbox

**Files:**

- Create: `memory/audit.py`
- Modify: `memory/backends/sqlite_store.py`
- Modify: `memory/service.py`
- Create: `tests/test_memory_audit_outbox.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-03.md`

**Interfaces:**

- Produces: `SQLiteMemoryStore.append_audit(actor: str, action: str, target_id: str, payload: dict) -> str`
- Produces: `SQLiteMemoryStore.enqueue_outbox(event_type: str, payload: dict, dedupe_key: str | None = None) -> str | None`
- Produces: `SQLiteMemoryStore.list_outbox(status: str | None = None) -> list[dict]`
- Modifies: `Memory.store` writes audit events
- Modifies: `Memory.store("history", value)` creates deduplicated `memory.semantic_candidate.created` outbox events

### 步骤

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory_audit_outbox.py` 写入：

```python
from pathlib import Path

from memory import Memory
from memory.backends.sqlite_store import SQLiteMemoryStore


def test_store_writes_audit_event(tmp_path: Path):
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    memory.store("reset_flag", True)

    counts = memory.debug_counts()
    assert counts.audit == 1


def test_history_append_creates_outbox_event(tmp_path: Path):
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    memory.store("history", [{"input": "喜欢安静酒店", "response": "已记录"}])

    counts = memory.debug_counts()
    assert counts.outbox == 1


def test_history_outbox_is_deduplicated(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    memory = Memory(config={"MEMORY_DB_PATH": str(db_path)})
    history = [{"input": "喜欢安静酒店", "response": "已记录"}]

    memory.store("history", history)
    memory.store("history", history)

    assert memory.debug_counts().outbox == 1


def test_list_outbox_returns_payload(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(str(db_path))

    event_id = store.enqueue_outbox(
        "memory.semantic_candidate.created",
        {"text": "用户喜欢安静酒店"},
        dedupe_key="turn:1",
    )

    rows = store.list_outbox()
    assert event_id is not None
    assert rows[0]["event_type"] == "memory.semantic_candidate.created"
    assert rows[0]["payload"]["text"] == "用户喜欢安静酒店"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_audit_outbox.py -v
```

Expected:

```text
FAILED tests/test_memory_audit_outbox.py::test_store_writes_audit_event
```

- [ ] **Step 3: 实现审计和 outbox schema**

在 `memory/audit.py` 写入：

```python
"""Audit constants for the Memory layer."""

ACTION_KV_STORED = "memory.kv.stored"
ACTION_OUTBOX_ENQUEUED = "memory.outbox.enqueued"
ACTION_MEMORY_FORGOTTEN = "memory.record.forgotten"
DEFAULT_ACTOR = "agent"
```

在 `SQLiteMemoryStore._ensure_schema()` 增加：

```sql
CREATE TABLE IF NOT EXISTS memory_outbox (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    dedupe_key TEXT UNIQUE,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

```sql
CREATE TABLE IF NOT EXISTS memory_audit_log (
    audit_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

在 `memory/backends/sqlite_store.py` 增加：

```python
import hashlib
import uuid
```

新增方法：

```python
def append_audit(self, actor: str, action: str, target_id: str, payload: dict[str, Any]) -> str:
    audit_id = uuid.uuid4().hex
    with self._connect() as conn:
        conn.execute(
            """
            INSERT INTO memory_audit_log (audit_id, actor, action, target_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (audit_id, actor, action, target_id, json.dumps(payload, ensure_ascii=False), self._now()),
        )
        conn.commit()
    return audit_id

def enqueue_outbox(
    self,
    event_type: str,
    payload: dict[str, Any],
    dedupe_key: str | None = None,
) -> str | None:
    event_id = uuid.uuid4().hex
    now = self._now()
    try:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_outbox (
                    event_id, event_type, payload_json, dedupe_key, status,
                    attempts, last_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False),
                    dedupe_key,
                    "pending",
                    0,
                    None,
                    now,
                    now,
                ),
            )
            conn.commit()
        return event_id
    except sqlite3.IntegrityError:
        return None

def list_outbox(self, status: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM memory_outbox"
    params = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at ASC"
    with self._connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"]),
            "dedupe_key": row["dedupe_key"],
            "status": row["status"],
            "attempts": row["attempts"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]

@staticmethod
def history_turn_dedupe_key(turn: object) -> str:
    raw = json.dumps(turn, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

更新 `counts()`：

```python
audit_count = conn.execute("SELECT COUNT(*) FROM memory_audit_log").fetchone()[0]
outbox_count = conn.execute("SELECT COUNT(*) FROM memory_outbox").fetchone()[0]
return DebugCounts(kv=kv_count, outbox=outbox_count, audit=audit_count)
```

- [ ] **Step 4: 连接 `Memory.store`**

在 `memory/service.py` 导入：

```python
from memory.audit import ACTION_KV_STORED, ACTION_OUTBOX_ENQUEUED, DEFAULT_ACTOR
```

在 `store()` 的 SQLite 分支中：

```python
if self._sqlite is not None:
    self._sqlite.set_kv(key, value)
    self._sqlite.append_audit(DEFAULT_ACTOR, ACTION_KV_STORED, key, {"key": key})
    if key == "history" and self.config.generate_memories:
        self._enqueue_history_candidates(value)
else:
    self._store[key] = value
```

新增私有方法：

```python
def _enqueue_history_candidates(self, value: object) -> None:
    if self._sqlite is None or not isinstance(value, list):
        return
    for turn in value:
        if not isinstance(turn, dict):
            continue
        text = f"Q: {turn.get('input', '')}\nA: {turn.get('response', '')}"
        dedupe_key = self._sqlite.history_turn_dedupe_key(turn)
        event_id = self._sqlite.enqueue_outbox(
            "memory.semantic_candidate.created",
            {
                "text": text,
                "key": "history",
                "tenant_id": self.config.tenant_id,
                "user_id": self.config.user_id,
                "project_id": self.config.project_id,
                "thread_id": self.config.thread_id,
            },
            dedupe_key=dedupe_key,
        )
        if event_id is not None:
            self._sqlite.append_audit(
                DEFAULT_ACTOR,
                ACTION_OUTBOX_ENQUEUED,
                event_id,
                {"event_type": "memory.semantic_candidate.created", "dedupe_key": dedupe_key},
            )
```

- [ ] **Step 5: 运行测试**

Run:

```bash
pytest tests/test_memory_audit_outbox.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 6: 运行回归测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py -v
```

Expected:

```text
11 passed
```

- [ ] **Step 7: 写第 3 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-03.md`

人工验证命令：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual.sqlite3"})
m.store("history", [{"input": "喜欢安静酒店", "response": "已记录"}])
print(m.debug_counts())
PY
```

预期：输出中的 `audit` 和 `outbox` 不是 0。

- [ ] **Step 8: 提交第 3 阶段**

Run:

```bash
git add memory/audit.py memory/backends/sqlite_store.py memory/service.py tests/test_memory_audit_outbox.py docs/superpowers/reports/2026-07-07-memory-phase-03.md
git commit -m "feat(memory): add audit log and semantic outbox"
```

Expected:

```text
[context <commit>] feat(memory): add audit log and semantic outbox
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 4。

---

## Task 4: 脱敏和记忆候选分类

**Files:**

- Create: `memory/redaction.py`
- Create: `memory/classifier.py`
- Create: `tests/test_memory_redaction_classifier.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-04.md`

**Interfaces:**

- Produces: `RedactionResult`
- Produces: `redact_text(text: str) -> RedactionResult`
- Produces: `MemoryClassification`
- Produces: `classify_memory_candidate(text: str) -> MemoryClassification`

### 步骤

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory_redaction_classifier.py` 写入：

```python
from memory.classifier import classify_memory_candidate
from memory.models import MemoryKind
from memory.redaction import redact_text


def test_redacts_openai_style_secret():
    result = redact_text("api key is sk-abcdefghijklmnopqrstuvwxyz123456")

    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result.text
    assert "[REDACTED:secret]" in result.text
    assert result.redacted is True


def test_redacts_bearer_token():
    result = redact_text("Authorization: Bearer abc.def.ghi")

    assert "abc.def.ghi" not in result.text
    assert "[REDACTED:bearer_token]" in result.text


def test_redacts_private_key_block():
    result = redact_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

    assert "BEGIN PRIVATE KEY" not in result.text
    assert "[REDACTED:private_key]" in result.text


def test_classifies_stable_preference_as_semantic():
    result = classify_memory_candidate("用户喜欢安静、交通方便的酒店")

    assert result.should_remember is True
    assert result.kind == MemoryKind.SEMANTIC
    assert result.importance >= 0.6


def test_classifies_workflow_as_procedural():
    result = classify_memory_candidate("以后每完成一步都写中文阶段报告并等待确认")

    assert result.should_remember is True
    assert result.kind == MemoryKind.PROCEDURAL


def test_skips_low_value_transient_message():
    result = classify_memory_candidate("好的")

    assert result.should_remember is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_redaction_classifier.py -v
```

Expected:

```text
FAILED tests/test_memory_redaction_classifier.py::test_redacts_openai_style_secret
```

- [ ] **Step 3: 扩展 models**

在 `memory/models.py` 增加：

```python
class RedactionResult(BaseModel):
    text: str
    redacted: bool = False
    markers: list[str] = Field(default_factory=list)


class MemoryClassification(BaseModel):
    should_remember: bool
    kind: MemoryKind = MemoryKind.EPISODIC
    confidence: float = 0.5
    importance: float = 0.5
    reason: str = ""
```

- [ ] **Step 4: 实现脱敏**

在 `memory/redaction.py` 写入：

```python
"""Sensitive data redaction for durable semantic memory."""

from __future__ import annotations

import re

from memory.models import RedactionResult


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]+")),
    ("secret", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("cookie", re.compile(r"(?i)(cookie|sessionid|session_token)\s*[:=]\s*[^;\s]+")),
]


def redact_text(text: str) -> RedactionResult:
    output = text
    markers: list[str] = []
    for name, pattern in PATTERNS:
        replacement = f"[REDACTED:{name}]"
        output, count = pattern.subn(replacement, output)
        if count:
            markers.append(name)
    return RedactionResult(text=output, redacted=bool(markers), markers=markers)
```

- [ ] **Step 5: 实现规则分类**

在 `memory/classifier.py` 写入：

```python
"""Rule-based memory candidate classifier."""

from __future__ import annotations

from memory.models import MemoryClassification, MemoryKind


PROCEDURAL_KEYWORDS = ("以后", "每次", "总是", "不要", "必须", "流程", "阶段报告", "等待确认")
PREFERENCE_KEYWORDS = ("喜欢", "偏好", "习惯", "希望", "倾向", "使用", "正在构建", "项目")


def classify_memory_candidate(text: str) -> MemoryClassification:
    stripped = text.strip()
    if len(stripped) < 6:
        return MemoryClassification(
            should_remember=False,
            kind=MemoryKind.EPISODIC,
            confidence=0.9,
            importance=0.1,
            reason="内容过短，通常不是稳定记忆",
        )

    if any(keyword in stripped for keyword in PROCEDURAL_KEYWORDS):
        return MemoryClassification(
            should_remember=True,
            kind=MemoryKind.PROCEDURAL,
            confidence=0.8,
            importance=0.8,
            reason="命中流程或工作方式偏好",
        )

    if any(keyword in stripped for keyword in PREFERENCE_KEYWORDS):
        return MemoryClassification(
            should_remember=True,
            kind=MemoryKind.SEMANTIC,
            confidence=0.75,
            importance=0.7,
            reason="命中稳定偏好或项目事实",
        )

    return MemoryClassification(
        should_remember=False,
        kind=MemoryKind.EPISODIC,
        confidence=0.6,
        importance=0.3,
        reason="未命中稳定记忆规则",
    )
```

- [ ] **Step 6: 运行测试**

Run:

```bash
pytest tests/test_memory_redaction_classifier.py -v
```

Expected:

```text
6 passed
```

- [ ] **Step 7: 运行回归测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py -v
```

Expected:

```text
17 passed
```

- [ ] **Step 8: 写第 4 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-04.md`

人工验证命令：

```bash
uv run python - <<'PY'
from memory.redaction import redact_text
print(redact_text("token=sk-abcdefghijklmnopqrstuvwxyz123456").text)
PY
```

预期：输出包含 `[REDACTED:secret]`，不包含原始 secret。

- [ ] **Step 9: 提交第 4 阶段**

Run:

```bash
git add memory/models.py memory/redaction.py memory/classifier.py tests/test_memory_redaction_classifier.py docs/superpowers/reports/2026-07-07-memory-phase-04.md
git commit -m "feat(memory): add redaction and candidate classification"
```

Expected:

```text
[context <commit>] feat(memory): add redaction and candidate classification
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 5。

---

## Task 5: BGE-M3 Embedding Provider

**Files:**

- Create: `memory/embeddings.py`
- Modify: `pyproject.toml`
- Create: `tests/test_memory_embeddings.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-05.md`

**Interfaces:**

- Produces: `EmbeddingProvider.embed(text: str) -> list[float]`
- Produces: `FakeEmbeddingProvider.embed(text: str) -> list[float]`
- Produces: `BGEM3EmbeddingProvider.embed(text: str) -> list[float]`

### 步骤

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory_embeddings.py` 写入：

```python
import pytest

from memory.embeddings import BGEM3EmbeddingProvider, FakeEmbeddingProvider


def test_fake_embedding_provider_is_deterministic():
    provider = FakeEmbeddingProvider(dimension=1024)

    first = provider.embed("我喜欢安静的酒店")
    second = provider.embed("我喜欢安静的酒店")

    assert len(first) == 1024
    assert first == second


def test_fake_embedding_provider_changes_with_text():
    provider = FakeEmbeddingProvider(dimension=1024)

    first = provider.embed("安静酒店")
    second = provider.embed("热闹餐厅")

    assert first != second


def test_bge_provider_loads_lazily():
    provider = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3", use_fp16=True)

    assert provider._model is None


def test_bge_provider_missing_dependency_error_is_clear(monkeypatch):
    provider = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")

    def fail_import():
        raise ImportError("No module named FlagEmbedding")

    monkeypatch.setattr(provider, "_import_model_class", fail_import)

    with pytest.raises(RuntimeError, match="FlagEmbedding"):
        provider.embed("测试")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_embeddings.py -v
```

Expected:

```text
FAILED tests/test_memory_embeddings.py::test_fake_embedding_provider_is_deterministic
```

- [ ] **Step 3: 声明依赖**

在 `pyproject.toml` 的 dependencies 中加入：

```toml
"FlagEmbedding>=1.2.11",
"numpy>=1.26",
```

如果执行阶段发现用户环境已安装但版本约束不兼容，阶段报告必须写明实际版本和调整原因。

- [ ] **Step 4: 实现 embedding providers**

在 `memory/embeddings.py` 写入：

```python
"""Embedding providers for semantic memory."""

from __future__ import annotations

import hashlib
import random
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for text."""


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 1024):
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed = int(digest[:16], 16)
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]


class BGEM3EmbeddingProvider:
    def __init__(self, model_name: str = "BAAI/bge-m3", use_fp16: bool = True, max_length: int = 8192):
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.max_length = max_length
        self._model = None

    def _import_model_class(self):
        from FlagEmbedding import BGEM3FlagModel

        return BGEM3FlagModel

    def _load_model(self):
        if self._model is None:
            try:
                model_class = self._import_model_class()
            except ImportError as exc:
                raise RuntimeError(
                    "FlagEmbedding is required for BGEM3EmbeddingProvider. "
                    "Install project dependencies before using BGE-M3 embeddings."
                ) from exc
            self._model = model_class(self.model_name, use_fp16=self.use_fp16)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load_model()
        output = model.encode([text], batch_size=1, max_length=self.max_length)
        dense = output["dense_vecs"][0]
        return [float(value) for value in dense]
```

- [ ] **Step 5: 运行 embedding 单元测试**

Run:

```bash
pytest tests/test_memory_embeddings.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 6: 可选真实 BGE-M3 人工烟测**

此命令不作为 CI 必须项，因为会加载大模型：

```bash
uv run python - <<'PY'
from memory.embeddings import BGEM3EmbeddingProvider
p = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")
v = p.embed("我喜欢安静的酒店")
print(len(v))
print(type(v[0]).__name__)
PY
```

预期：

```text
1024
float
```

- [ ] **Step 7: 跑回归测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py -v
```

Expected:

```text
21 passed
```

- [ ] **Step 8: 写第 5 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-05.md`

报告必须说明：

- `FakeEmbeddingProvider` 用于自动测试。
- `BGEM3EmbeddingProvider` 懒加载模型。
- 真实 BGE-M3 烟测是否执行。
- 如果真实烟测未执行，说明原因和用户可手动执行的命令。

- [ ] **Step 9: 提交第 5 阶段**

Run:

```bash
git add pyproject.toml memory/embeddings.py tests/test_memory_embeddings.py docs/superpowers/reports/2026-07-07-memory-phase-05.md
git commit -m "feat(memory): add bge-m3 embedding provider"
```

Expected:

```text
[context <commit>] feat(memory): add bge-m3 embedding provider
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 6。

---

## Task 6: Qdrant 向量索引后端

**Files:**

- Create: `memory/backends/qdrant_store.py`
- Modify: `pyproject.toml`
- Create: `tests/test_memory_qdrant_store.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-06.md`

**Interfaces:**

- Produces: `QdrantMemoryIndex.ensure_collection() -> None`
- Produces: `QdrantMemoryIndex.upsert_memory(record: MemoryRecord, vector: list[float]) -> None`
- Produces: `QdrantMemoryIndex.search(vector: list[float], filters: dict, top_k: int) -> list[dict]`
- Produces: `QdrantMemoryIndex.delete_memory(memory_id: str) -> None`

### 步骤

- [ ] **Step 1: 写 Qdrant 后端测试**

在 `tests/test_memory_qdrant_store.py` 写入：

```python
from datetime import datetime

from memory.backends.qdrant_store import QdrantMemoryIndex
from memory.models import MemoryKind, MemoryRecord, MemoryScope


class FakeQdrantClient:
    def __init__(self):
        self.collections = {}
        self.points = {}
        self.deleted = []

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, vectors_config):
        self.collections[collection_name] = vectors_config

    def upsert(self, collection_name, points):
        self.points.setdefault(collection_name, {})
        for point in points:
            self.points[collection_name][point.id] = point

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        class Result:
            def __init__(self, points):
                self.points = points

        class Point:
            def __init__(self, point_id, payload):
                self.id = point_id
                self.payload = payload
                self.score = 0.9

        points = [
            Point(point.id, point.payload)
            for point in self.points.get(collection_name, {}).values()
        ][:limit]
        return Result(points)

    def delete(self, collection_name, points_selector):
        self.deleted.append((collection_name, points_selector))


def make_record():
    return MemoryRecord(
        memory_id="mem_1",
        tenant_id="local",
        user_id="default",
        project_id="lazyaiX-agent-corp-1",
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.SEMANTIC,
        content="用户喜欢安静酒店",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_ensure_collection_creates_1024_cosine_collection():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(client=client, collection_name="agent_memories_v1", vector_size=1024)

    index.ensure_collection()

    config = client.collections["agent_memories_v1"]
    assert config.size == 1024
    assert config.distance.value == "Cosine"


def test_upsert_memory_writes_payload():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(client=client, collection_name="agent_memories_v1", vector_size=1024)
    record = make_record()

    index.upsert_memory(record, [0.1] * 1024)

    point = client.points["agent_memories_v1"]["mem_1"]
    assert point.payload["memory_id"] == "mem_1"
    assert point.payload["tenant_id"] == "local"
    assert point.payload["project_id"] == "lazyaiX-agent-corp-1"
    assert point.payload["status"] == "active"


def test_search_returns_payload_results():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(client=client, collection_name="agent_memories_v1", vector_size=1024)
    index.upsert_memory(make_record(), [0.1] * 1024)

    results = index.search([0.1] * 1024, {"tenant_id": "local"}, top_k=3)

    assert results[0]["memory_id"] == "mem_1"
    assert results[0]["score"] == 0.9


def test_delete_memory_calls_qdrant_delete():
    client = FakeQdrantClient()
    index = QdrantMemoryIndex(client=client, collection_name="agent_memories_v1", vector_size=1024)

    index.delete_memory("mem_1")

    assert client.deleted
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_qdrant_store.py -v
```

Expected:

```text
FAILED tests/test_memory_qdrant_store.py::test_ensure_collection_creates_1024_cosine_collection
```

- [ ] **Step 3: 声明 qdrant-client 依赖**

在 `pyproject.toml` dependencies 中加入：

```toml
"qdrant-client>=1.10.0",
```

- [ ] **Step 4: 实现 Qdrant 后端**

在 `memory/backends/qdrant_store.py` 写入：

```python
"""Qdrant vector index backend for semantic memories."""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, FieldCondition, MatchValue, PointIdsList, PointStruct, VectorParams

from memory.models import MemoryRecord


class QdrantMemoryIndex:
    def __init__(
        self,
        client: QdrantClient | None = None,
        url: str = "http://localhost:6333",
        collection_name: str = "agent_memories_v1",
        vector_size: int = 1024,
    ):
        self.client = client or QdrantClient(url=url)
        self.collection_name = collection_name
        self.vector_size = vector_size

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
        )

    @staticmethod
    def _payload(record: MemoryRecord) -> dict[str, Any]:
        return {
            "memory_id": record.memory_id,
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "project_id": record.project_id,
            "thread_id": record.thread_id,
            "scope": record.scope.value,
            "kind": record.kind.value,
            "status": record.status.value,
            "confidence": record.confidence,
            "importance": record.importance,
            "sensitivity": record.sensitivity,
            "source_id": record.source_id,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        }

    def upsert_memory(self, record: MemoryRecord, vector: list[float]) -> None:
        self.ensure_collection()
        point = PointStruct(id=record.memory_id, vector=vector, payload=self._payload(record))
        self.client.upsert(collection_name=self.collection_name, points=[point])

    @staticmethod
    def _filter(filters: dict[str, Any]) -> Filter | None:
        conditions = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in filters.items()
            if value is not None
        ]
        if not conditions:
            return None
        return Filter(must=conditions)

    def search(self, vector: list[float], filters: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
        self.ensure_collection()
        result = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=self._filter(filters),
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "id": point.id,
                "score": float(point.score),
                **(point.payload or {}),
            }
            for point in result.points
        ]

    def delete_memory(self, memory_id: str) -> None:
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[memory_id]),
        )
```

- [ ] **Step 5: 运行 Qdrant 后端测试**

Run:

```bash
pytest tests/test_memory_qdrant_store.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 6: 可选本地 Qdrant 人工烟测**

确认 Qdrant 服务可用：

```bash
curl -s http://localhost:6333/collections
```

预期：返回 JSON，包含 `collections` 字段。

- [ ] **Step 7: 运行回归测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py tests/test_memory_qdrant_store.py -v
```

Expected:

```text
25 passed
```

- [ ] **Step 8: 写第 6 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-06.md`

报告必须说明：

- collection 名称
- vector size 和 distance
- payload 字段
- 是否执行了真实 Qdrant 烟测

- [ ] **Step 9: 提交第 6 阶段**

Run:

```bash
git add pyproject.toml memory/backends/qdrant_store.py tests/test_memory_qdrant_store.py docs/superpowers/reports/2026-07-07-memory-phase-06.md
git commit -m "feat(memory): add qdrant vector index backend"
```

Expected:

```text
[context <commit>] feat(memory): add qdrant vector index backend
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 7。

---

## Task 7: `remember`、`search`、`forget` 语义记忆闭环

**Files:**

- Create: `memory/retrieval.py`
- Modify: `memory/backends/sqlite_store.py`
- Modify: `memory/service.py`
- Create: `tests/test_memory_service_semantic.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-07.md`

**Interfaces:**

- Produces: `SQLiteMemoryStore.insert_source(source: SourceRef) -> str`
- Produces: `SQLiteMemoryStore.insert_record(record: MemoryRecord) -> str`
- Produces: `SQLiteMemoryStore.get_record(memory_id: str) -> MemoryRecord | None`
- Produces: `SQLiteMemoryStore.list_records(memory_ids: list[str]) -> list[MemoryRecord]`
- Produces: `SQLiteMemoryStore.mark_deleted(memory_id: str) -> bool`
- Produces: `Memory.remember(content, kind, scope, metadata, source) -> str`
- Produces: `Memory.search(query, top_k, scope, project_id, include_sources) -> list[MemorySearchResult]`
- Produces: `Memory.forget(memory_id, reason) -> bool`

### 步骤

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory_service_semantic.py` 写入：

```python
from pathlib import Path

from memory import Memory
from memory.embeddings import FakeEmbeddingProvider


class FakeIndex:
    def __init__(self):
        self.points = {}
        self.deleted = set()

    def upsert_memory(self, record, vector):
        self.points[record.memory_id] = {"record": record, "vector": vector}

    def search(self, vector, filters, top_k):
        results = []
        for memory_id, item in self.points.items():
            record = item["record"]
            if memory_id in self.deleted:
                continue
            if record.tenant_id != filters.get("tenant_id"):
                continue
            if record.user_id != filters.get("user_id"):
                continue
            if record.project_id != filters.get("project_id"):
                continue
            if record.status.value != "active":
                continue
            results.append({"memory_id": memory_id, "score": 0.9})
        return results[:top_k]

    def delete_memory(self, memory_id):
        self.deleted.add(memory_id)


def make_memory(tmp_path: Path):
    return Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
    )


def test_remember_creates_searchable_memory(tmp_path: Path):
    memory = make_memory(tmp_path)

    memory_id = memory.remember("用户喜欢安静、交通方便的酒店", kind="semantic")
    results = memory.search("住宿偏好", top_k=3)

    assert memory_id
    assert results[0].memory_id == memory_id
    assert results[0].content == "用户喜欢安静、交通方便的酒店"


def test_search_filters_project_by_default(tmp_path: Path):
    memory = make_memory(tmp_path)
    other = Memory(
        config={
            "MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3"),
            "MEMORY_PROJECT_ID": "other-project",
        },
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=memory._vector_index,
    )

    memory.remember("当前项目偏好 Qdrant", kind="semantic")
    other.remember("其他项目偏好 Milvus", kind="semantic")

    results = memory.search("项目向量库", top_k=10)

    assert [result.content for result in results] == ["当前项目偏好 Qdrant"]


def test_forget_hides_memory_from_search(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory_id = memory.remember("用户喜欢安静酒店", kind="semantic")

    assert memory.forget(memory_id, reason="人工删除") is True

    assert memory.search("酒店", top_k=3) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_service_semantic.py -v
```

Expected:

```text
FAILED tests/test_memory_service_semantic.py::test_remember_creates_searchable_memory
```

- [ ] **Step 3: 实现 SQLite records/sources schema**

在 `SQLiteMemoryStore._ensure_schema()` 中增加 `memory_records` 和 `memory_sources` 表，字段必须覆盖 spec 中第 10.1 节。

新增方法必须把 Pydantic 模型转换为 SQLite 行，并能从 SQLite 行恢复模型。

关键实现要求：

```python
def insert_source(self, source: SourceRef) -> str:
    with self._connect() as conn:
        conn.execute(
            "INSERT INTO memory_sources (source_id, source_type, source_ref, excerpt, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                source.source_id,
                source.source_type,
                source.source_ref,
                source.excerpt,
                json.dumps(source.metadata, ensure_ascii=False),
                source.created_at.isoformat(),
            ),
        )
        conn.commit()
    return source.source_id

def insert_record(self, record: MemoryRecord) -> str:
    with self._connect() as conn:
        conn.execute(
            "INSERT INTO memory_records (memory_id, tenant_id, user_id, project_id, thread_id, scope, kind, content, metadata_json, status, confidence, importance, sensitivity, source_id, created_at, updated_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.memory_id,
                record.tenant_id,
                record.user_id,
                record.project_id,
                record.thread_id,
                record.scope.value,
                record.kind.value,
                record.content,
                json.dumps(record.metadata, ensure_ascii=False),
                record.status.value,
                record.confidence,
                record.importance,
                record.sensitivity,
                record.source_id,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
                record.expires_at.isoformat() if record.expires_at else None,
            ),
        )
        conn.commit()
    return record.memory_id

def get_record(self, memory_id: str) -> MemoryRecord | None:
    row = self._fetch_record_row(memory_id)
    return self._record_from_row(row) if row is not None else None

def list_records(self, memory_ids: list[str]) -> list[MemoryRecord]:
    return [
        record
        for memory_id in memory_ids
        if (record := self.get_record(memory_id)) is not None
    ]

def mark_deleted(self, memory_id: str) -> bool:
    with self._connect() as conn:
        cursor = conn.execute(
            "UPDATE memory_records SET status = ?, updated_at = ? WHERE memory_id = ? AND status != ?",
            ("deleted", self._now(), memory_id, "deleted"),
        )
        conn.commit()
    return cursor.rowcount > 0
```

实现中不能把 semantic memory 存为 pickle。`metadata` 必须用 JSON。

- [ ] **Step 4: 实现 retrieval helper**

在 `memory/retrieval.py` 写入：

```python
"""Retrieval helpers for semantic memory search."""

from __future__ import annotations

from memory.models import MemoryRecord


def combined_score(vector_score: float, record: MemoryRecord) -> float:
    importance_bonus = record.importance * 0.1
    confidence_bonus = record.confidence * 0.1
    return vector_score + importance_bonus + confidence_bonus
```

- [ ] **Step 5: 连接 `Memory.remember/search/forget`**

修改 `Memory.__init__` 支持注入：

```python
def __init__(
    self,
    config: dict[str, Any] | MemoryConfig | None = None,
    embedding_provider: Any | None = None,
    vector_index: Any | None = None,
):
```

当未注入时：

- `embedding_provider` 使用 `BGEM3EmbeddingProvider`
- `vector_index` 使用 `QdrantMemoryIndex`

测试中使用 fake 注入，避免加载真实模型和访问真实 Qdrant。

新增 `remember()`：

```python
def remember(
    self,
    content: str,
    *,
    kind: str = "semantic",
    scope: str = "project",
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> str:
    metadata = metadata or {}
    source = source or {}
    redacted = redact_text(content) if self.config.redact_secrets else RedactionResult(text=content)
    memory_id = f"mem_{uuid.uuid4().hex}"
    source_ref = SourceRef(
        source_id=f"src_{uuid.uuid4().hex}",
        source_type=str(source.get("source_type", "manual")),
        source_ref=str(source.get("source_ref", "")),
        excerpt=redacted.text[:500],
        metadata=source,
    )
    record = MemoryRecord(
        memory_id=memory_id,
        tenant_id=self.config.tenant_id,
        user_id=self.config.user_id,
        project_id=self.config.project_id,
        thread_id=self.config.thread_id,
        scope=MemoryScope(scope),
        kind=MemoryKind(kind),
        content=redacted.text,
        metadata=metadata,
        source_id=source_ref.source_id,
    )
    self._sqlite.insert_source(source_ref)
    self._sqlite.insert_record(record)
    vector = self._embedding_provider.embed(redacted.text)
    self._vector_index.upsert_memory(record, vector)
    self._sqlite.append_audit(DEFAULT_ACTOR, "memory.record.remembered", memory_id, {"kind": kind, "scope": scope})
    return memory_id
```

要求：

- 生成 `memory_id`
- redaction 后保存 content
- 创建 source
- 创建 SQLite record
- 生成 embedding
- upsert Qdrant
- 写 audit
- 返回 `memory_id`

新增 `search()`：

```python
def search(
    self,
    query: str,
    *,
    top_k: int = 5,
    scope: str | None = None,
    project_id: str | None = None,
    include_sources: bool = True,
) -> list[MemorySearchResult]:
    if not self.config.use_memories:
        return []
    vector = self._embedding_provider.embed(query)
    filters = {
        "tenant_id": self.config.tenant_id,
        "user_id": self.config.user_id,
        "project_id": project_id or self.config.project_id,
        "status": "active",
    }
    if scope is not None:
        filters["scope"] = scope
    hits = self._vector_index.search(vector, filters, top_k)
    records = self._sqlite.list_records([str(hit["memory_id"]) for hit in hits])
    record_by_id = {record.memory_id: record for record in records if record.status == MemoryStatus.ACTIVE}
    results = []
    for hit in hits:
        record = record_by_id.get(str(hit["memory_id"]))
        if record is None:
            continue
        results.append(
            MemorySearchResult(
                memory_id=record.memory_id,
                content=record.content,
                kind=record.kind,
                scope=record.scope,
                score=combined_score(float(hit["score"]), record),
                source=None,
                metadata=record.metadata,
            )
        )
    return sorted(results, key=lambda result: result.score, reverse=True)
```

要求：

- `MEMORY_USE_MEMORIES=false` 时返回空列表
- filters 默认包含 tenant/user/project/status
- SQLite 记录为 deleted 时过滤掉
- 返回 `MemorySearchResult`

新增 `forget()`：

```python
def forget(self, memory_id: str, *, reason: str = "") -> bool:
    changed = self._sqlite.mark_deleted(memory_id)
    if changed:
        self._vector_index.delete_memory(memory_id)
        self._sqlite.append_audit(DEFAULT_ACTOR, ACTION_MEMORY_FORGOTTEN, memory_id, {"reason": reason})
    return changed
```

要求：

- SQLite mark deleted
- Qdrant delete
- 写 tombstone record 或 audit payload 中记录 reason
- 返回是否删除成功

- [ ] **Step 6: 运行语义服务测试**

Run:

```bash
pytest tests/test_memory_service_semantic.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 7: 运行全部已有 memory 测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py tests/test_memory_qdrant_store.py tests/test_memory_service_semantic.py -v
```

Expected:

```text
28 passed
```

- [ ] **Step 8: 人工验证**

Run:

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
mid = m.remember("用户喜欢安静、交通方便的酒店", kind="semantic")
print("id", mid)
print([r.content for r in m.search("住宿偏好", top_k=3)])
m.forget(mid, reason="manual test")
print(m.search("住宿偏好", top_k=3))
PY
```

预期：

- 第一次 search 返回酒店偏好。
- `forget()` 后 search 不再返回这条记忆。

- [ ] **Step 9: 写第 7 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-07.md`

报告必须说明：

- SQLite 哪些表保存 semantic memory
- Qdrant 保存了什么 payload
- search 如何做 scope filter
- forget 如何阻止记忆再次出现
- 是否执行了真实 BGE-M3 + Qdrant 人工验证

- [ ] **Step 10: 提交第 7 阶段**

Run:

```bash
git add memory/backends/sqlite_store.py memory/retrieval.py memory/service.py tests/test_memory_service_semantic.py docs/superpowers/reports/2026-07-07-memory-phase-07.md
git commit -m "feat(memory): add semantic remember search and forget"
```

Expected:

```text
[context <commit>] feat(memory): add semantic remember search and forget
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 8。

---

## Task 8: Summary、Import、Export

**Files:**

- Create: `memory/exporter.py`
- Modify: `memory/backends/sqlite_store.py`
- Modify: `memory/service.py`
- Create: `tests/test_memory_import_export_summary.py`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-08.md`

**Interfaces:**

- Produces: `Memory.get_summary(scope: str = "project") -> str`
- Produces: `Memory.update_summary(summary: str, scope: str = "project") -> None`
- Produces: `Memory.export(format: str = "markdown") -> str`
- Produces: `Memory.import_memories(content: str, source: str = "manual") -> list[str]`

### 步骤

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory_import_export_summary.py` 写入：

```python
from pathlib import Path

from memory import Memory
from memory.embeddings import FakeEmbeddingProvider


class FakeIndex:
    def __init__(self):
        self.points = {}

    def upsert_memory(self, record, vector):
        self.points[record.memory_id] = record

    def search(self, vector, filters, top_k):
        return []

    def delete_memory(self, memory_id):
        self.points.pop(memory_id, None)


def make_memory(tmp_path: Path):
    return Memory(
        config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")},
        embedding_provider=FakeEmbeddingProvider(),
        vector_index=FakeIndex(),
    )


def test_summary_round_trip(tmp_path: Path):
    memory = make_memory(tmp_path)

    memory.update_summary("用户正在构建企业级本地记忆系统。")

    assert memory.get_summary() == "用户正在构建企业级本地记忆系统。"


def test_markdown_export_contains_summary_and_memory(tmp_path: Path):
    memory = make_memory(tmp_path)
    memory.update_summary("用户偏好中文阶段报告。")
    memory.remember("用户使用 Qdrant 和 BGE-M3 构建记忆系统", kind="semantic")

    exported = memory.export("markdown")

    assert "# Memory Export" in exported
    assert "## Summary" in exported
    assert "用户偏好中文阶段报告。" in exported
    assert "用户使用 Qdrant 和 BGE-M3 构建记忆系统" in exported


def test_jsonl_export_import_round_trip(tmp_path: Path):
    source = make_memory(tmp_path / "source")
    target = make_memory(tmp_path / "target")
    source.remember("用户喜欢小步提交", kind="procedural")

    exported = source.export("jsonl")
    ids = target.import_memories(exported, source="jsonl_test")

    assert len(ids) == 1
    assert target.search("小步提交", top_k=3)[0].content == "用户喜欢小步提交"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_memory_import_export_summary.py -v
```

Expected:

```text
FAILED tests/test_memory_import_export_summary.py::test_summary_round_trip
```

- [ ] **Step 3: 实现 summary schema 和 store 方法**

在 `SQLiteMemoryStore._ensure_schema()` 增加 `memory_summaries` 表。

新增：

```python
def upsert_summary(self, tenant_id: str, user_id: str, project_id: str, scope: str, content: str) -> None:
    now = self._now()
    with self._connect() as conn:
        conn.execute(
            "INSERT INTO memory_summaries (summary_id, tenant_id, user_id, project_id, scope, content, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tenant_id, user_id, project_id, scope) DO UPDATE SET content = excluded.content, version = memory_summaries.version + 1, updated_at = excluded.updated_at",
            (uuid.uuid4().hex, tenant_id, user_id, project_id, scope, content, 1, now, now),
        )
        conn.commit()

def get_summary(self, tenant_id: str, user_id: str, project_id: str, scope: str) -> str:
    with self._connect() as conn:
        row = conn.execute(
            "SELECT content FROM memory_summaries WHERE tenant_id = ? AND user_id = ? AND project_id = ? AND scope = ?",
            (tenant_id, user_id, project_id, scope),
        ).fetchone()
    return str(row["content"]) if row is not None else ""

def list_active_records(self) -> list[MemoryRecord]:
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM memory_records WHERE status = ? ORDER BY created_at ASC",
            ("active",),
        ).fetchall()
    return [self._record_from_row(row) for row in rows]
```

更新 `counts()` 支持 `summaries`。

- [ ] **Step 4: 实现 exporter**

在 `memory/exporter.py` 写入：

```python
"""Import and export helpers for Memory."""

from __future__ import annotations

import json

from memory.models import MemoryRecord


def export_markdown(summary: str, records: list[MemoryRecord]) -> str:
    lines = [
        "# Memory Export",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Durable Memories",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"- [{record.memory_id}] {record.content}",
                f"  - kind: {record.kind.value}",
                f"  - scope: {record.scope.value}",
                f"  - source: {record.source_id or ''}",
            ]
        )
    lines.extend(["", "## Deleted Memories", "", ""])
    return "\n".join(lines)


def export_jsonl(records: list[MemoryRecord]) -> str:
    return "\n".join(record.model_dump_json() for record in records)


def parse_jsonl(content: str) -> list[dict]:
    rows: list[dict] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows
```

- [ ] **Step 5: 连接 Memory summary/import/export**

在 `Memory` 中新增：

```python
def get_summary(self, *, scope: str = "project") -> str:
    return self._sqlite.get_summary(
        self.config.tenant_id,
        self.config.user_id,
        self.config.project_id,
        scope,
    )

def update_summary(self, summary: str, *, scope: str = "project") -> None:
    self._sqlite.upsert_summary(
        self.config.tenant_id,
        self.config.user_id,
        self.config.project_id,
        scope,
        summary,
    )

def export(self, format: str = "markdown") -> str:
    records = self._sqlite.list_active_records()
    if format == "markdown":
        return export_markdown(self.get_summary(), records)
    if format == "jsonl":
        return export_jsonl(records)
    raise ValueError(f"Unsupported export format: {format}")

def import_memories(self, content: str, *, source: str = "manual") -> list[str]:
    created_ids: list[str] = []
    if content.lstrip().startswith("{"):
        for row in parse_jsonl(content):
            created_ids.append(
                self.remember(
                    str(row["content"]),
                    kind=str(row.get("kind", "semantic")),
                    scope=str(row.get("scope", "project")),
                    metadata=dict(row.get("metadata", {})),
                    source={"source_type": source},
                )
            )
        return created_ids
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            created_ids.append(self.remember(stripped[2:], source={"source_type": source}))
    if not created_ids:
        raise ValueError("No importable memories found")
    return created_ids
```

要求：

- `format` 仅支持 `markdown` 和 `jsonl`。
- `jsonl` import 使用 `remember()` 重建 active records。
- Markdown import 第一版只接收 `- content` 风格的 durable memory 行；如果无法解析，抛出 `ValueError`。
- import 前走 redaction。

- [ ] **Step 6: 运行 import/export 测试**

Run:

```bash
pytest tests/test_memory_import_export_summary.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 7: 运行全部 memory 测试**

Run:

```bash
pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py tests/test_memory_embeddings.py tests/test_memory_qdrant_store.py tests/test_memory_service_semantic.py tests/test_memory_import_export_summary.py -v
```

Expected:

```text
31 passed
```

- [ ] **Step 8: 人工验证**

Run:

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
m.update_summary("用户正在构建企业级本地记忆系统。")
print(m.get_summary())
print(m.export("markdown")[:500])
PY
```

预期：输出包含 summary 和 `# Memory Export`。

- [ ] **Step 9: 写第 8 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-08.md`

报告必须说明：

- 如何查看 summary
- 如何编辑 summary
- markdown 导出结构
- jsonl 导入导出限制

- [ ] **Step 10: 提交第 8 阶段**

Run:

```bash
git add memory/exporter.py memory/backends/sqlite_store.py memory/service.py tests/test_memory_import_export_summary.py docs/superpowers/reports/2026-07-07-memory-phase-08.md
git commit -m "feat(memory): add summary import and export"
```

Expected:

```text
[context <commit>] feat(memory): add summary import and export
```

**停止点：** 向用户发送中文阶段报告摘要，请求确认是否进入 Task 9。

---

## Task 9: 现有 Agent 契约集成验证

**Files:**

- Create: `tests/test_memory_integration_with_agent_contract.py`
- Modify: `.gitignore`
- Create: `docs/superpowers/reports/2026-07-07-memory-phase-09.md`

**Interfaces:**

- Consumes: `Memory.store`
- Consumes: `Memory.retrieve`
- Consumes: `Agent(context, memory)`
- Produces: integration proof that existing callers do not need changes

### 步骤

- [ ] **Step 1: 写集成测试**

在 `tests/test_memory_integration_with_agent_contract.py` 写入：

```python
from pathlib import Path

from agent import Agent
from context import Context
from memory import Memory


def test_agent_uses_real_memory_without_code_changes(tmp_path: Path):
    context = Context()
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})
    agent = Agent(context=context, memory=memory)
    agent.model.complete = lambda prompt: "测试回复"
    agent.skill.decide = lambda user_input, llm_response, context, memory: {
        "action": "direct",
        "response": "测试回复",
    }

    response = agent.process_turn("你好")

    assert response == "测试回复"
    assert memory.retrieve("history") == [{"input": "你好", "response": "测试回复"}]


def test_travel_skill_keys_round_trip(tmp_path: Path):
    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    memory.store("current_requirement", {"destination": "成都", "days": 3, "budget": 3000})
    memory.store("current_itinerary", None)
    memory.store("reset_flag", True)

    restored = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    assert restored.retrieve("current_requirement") == {"destination": "成都", "days": 3, "budget": 3000}
    assert restored.retrieve("current_itinerary") is None
    assert restored.retrieve("reset_flag") is True
```

- [ ] **Step 2: 运行测试确认集成状态**

Run:

```bash
pytest tests/test_memory_integration_with_agent_contract.py -v
```

Expected:

```text
2 passed
```

如果失败，必须只修 `memory/` 层，不改 `agent.py` 或 `skills/`。

- [ ] **Step 3: 更新 `.gitignore`**

在 `.gitignore` 加入：

```gitignore
.memory/
```

- [ ] **Step 4: 运行全部测试**

Run:

```bash
pytest -v
```

Expected:

```text
所有测试通过
```

实际测试数量以当前仓库为准。阶段报告必须记录完整 pytest 结果。

- [ ] **Step 5: 人工 REPL 验证**

Run:

```bash
python3 loop.py
```

输入：

```text
我想去成都
玩3天
预算3000元
quit
```

预期：

- REPL 可以正常启动。
- 输入不会因为 `Memory` 真实实现而崩溃。
- `.memory/memory.sqlite3` 被创建。
- 退出后重新运行 Python 能读取 `history`。

验证读取命令：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
print(m.retrieve("history"))
print(m.debug_counts())
PY
```

- [ ] **Step 6: 写第 9 阶段中文报告**

Create: `docs/superpowers/reports/2026-07-07-memory-phase-09.md`

报告必须说明：

- 是否改动了非 memory 模块
- `Agent` 现有契约是否保持
- `history` 是否持久化
- 旅游业务 key 是否持久化
- 全量测试结果
- REPL 人工验证结果

- [ ] **Step 7: 提交第 9 阶段**

Run:

```bash
git add .gitignore tests/test_memory_integration_with_agent_contract.py docs/superpowers/reports/2026-07-07-memory-phase-09.md
git commit -m "test(memory): verify agent contract integration"
```

Expected:

```text
[context <commit>] test(memory): verify agent contract integration
```

**停止点：** 向用户发送中文最终阶段报告摘要，请求确认是否做收尾检查。

---

## 最终收尾检查

完成 Task 9 后执行：

```bash
git status --short
pytest -v
uv run python - <<'PY'
from memory import Memory
m = Memory()
print(type(m).__name__)
print(m.debug_counts())
PY
```

预期：

- `git status --short` 没有未提交变更，除非用户明确允许保留。
- `pytest -v` 全部通过。
- `Memory` 能实例化并返回 `DebugCounts`。

最终中文交付总结必须包含：

- 所有阶段 commit 列表
- 所有阶段报告路径
- 最终公开接口列表
- 用户人工验证入口
- 已知限制
- 下一步建议

---

## 计划自检

### Spec 覆盖

- 兼容接口：Task 1、Task 2、Task 9 覆盖。
- SQLite 持久化：Task 2 覆盖。
- 审计和 outbox：Task 3 覆盖。
- 脱敏和分类：Task 4 覆盖。
- BGE-M3：Task 5 覆盖。
- Qdrant：Task 6 覆盖。
- remember/search/forget：Task 7 覆盖。
- summary/import/export：Task 8 覆盖。
- 现有 Agent 不改动集成：Task 9 覆盖。
- 中文计划和报告：Global Constraints、每个 Task 的报告步骤覆盖。
- 每阶段人工审批：执行规则和每个 Task 停止点覆盖。

### 占位检查

本计划不保留未决实现项。执行阶段如果发现依赖版本或 Qdrant API 与本计划不一致，必须在当前阶段报告中记录实际情况、修改原因和验证结果。

### 类型一致性

- `Memory.store(key: str, value: object) -> None` 在所有阶段保持不变。
- `Memory.retrieve(key: str) -> object | None` 在所有阶段保持不变。
- `Memory.search(query, top_k, scope, project_id, include_sources) -> list[MemorySearchResult]` 从 Task 7 开始稳定。
- `DebugCounts` 由 `memory.models` 定义，并由 `Memory.debug_counts()` 返回。
- `MemoryRecord`、`SourceRef`、`MemorySearchResult` 由 `memory.models` 定义，并被 SQLite、Qdrant、exporter 共享。
