# 第 1 阶段报告：配置和公开接口骨架

## 本阶段目标

建立真实 `memory/` 模块入口和公开接口骨架，让现有代码可以通过 `from memory import Memory` 使用真实 `Memory` 类，同时不接入 SQLite、Qdrant 或 BGE-M3。

## 本阶段改动

- 新增 `Memory` facade，提供兼容接口 `store()` 和 `retrieve()`。
- 新增配置模型 `MemoryConfig`，统一读取环境变量和调用方覆盖配置。
- 新增记忆系统核心 Pydantic 模型和枚举。
- 新增接口测试，采用 TDD：先验证缺少接口时失败，再实现最小代码让测试通过。
- 修正实施计划中的人工验证命令，把裸 `python3` 统一改为 `uv run python`。

## 新增文件

- `memory/__init__.py`
- `memory/config.py`
- `memory/models.py`
- `memory/service.py`
- `tests/test_memory_interface.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-01.md`

## 修改文件

- `docs/superpowers/plans/2026-07-07-enterprise-memory-layer.md`

## 公开接口

- `memory.Memory`
- `Memory.store(key: str, value: object) -> None`
- `Memory.retrieve(key: str) -> object | None`
- `Memory.debug_counts() -> DebugCounts`
- `MemoryConfig.from_env(overrides: dict | None = None) -> MemoryConfig`
- `MemoryScope`
- `MemoryKind`
- `MemoryStatus`
- `SourceRef`
- `MemoryRecord`
- `MemorySearchResult`
- `DebugCounts`

## 自动验证

命令：

```bash
uv run pytest tests/test_memory_interface.py -v
```

结果：

```text
4 passed in 0.03s
```

命令：

```bash
uv run pytest -q
```

结果：

```text
59 passed in 0.18s
```

RED 验证记录：

```text
tests/test_memory_interface.py::test_memory_imports_real_class FAILED
tests/test_memory_interface.py::test_store_retrieve_in_memory_before_sqlite_backend FAILED
tests/test_memory_interface.py::test_default_config_values FAILED
tests/test_memory_enums_are_stable FAILED
```

失败原因是 `Memory`、`memory.config`、`memory.models` 尚不存在，符合第 1 阶段测试意图。第一次运行时顶层 import 造成 pytest collection error，随后已把 import 移入测试函数，让失败落在测试用例本身，符合 TDD 验证要求。

## 人工验证

步骤：

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

实际结果：

```text
{'world': 1}
```

说明：计划中的裸 `python3` 命令在当前机器上无法导入 `pydantic`，因为项目依赖安装在 `uv` 创建的虚拟环境中；本阶段及后续阶段的人工验证命令应优先使用 `uv run python`。

## 已知限制

- 当前阶段只提供内存字典实现，进程退出后数据不会保留。
- 当前阶段尚未接入 SQLite。
- 当前阶段尚未接入 Qdrant。
- 当前阶段尚未接入 BGE-M3。
- 当前阶段不提供 `remember()`、`search()`、`forget()`、summary、import/export。

## 请求确认

请审阅本阶段结果，并确认是否进入第 2 阶段：SQLite 兼容 KV 持久化。
