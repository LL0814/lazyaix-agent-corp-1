# 第 2 阶段报告：SQLite 兼容 KV 持久化

## 本阶段目标

把第 1 阶段的临时内存字典升级为 SQLite 兼容 KV 存储，让现有 `Memory.store(key, value)` 和 `Memory.retrieve(key)` 可以跨 `Memory` 实例、跨 Python 进程保留数据。

## 本阶段改动

- 新增 `SQLiteMemoryStore`，负责本地 SQLite 表创建、KV 写入、KV 读取和调试计数。
- `Memory` 默认后端从 `memory` 切换为 `sqlite`。
- 保留 `MEMORY_BACKEND=memory` 模式，用于测试、降级和不需要落盘的场景。
- `MemoryConfig.from_env()` 支持环境变量风格的覆盖参数，例如 `MEMORY_BACKEND`、`MEMORY_DB_PATH`。
- 新增 SQLite 持久化测试，覆盖 JSON 值、非 JSON 本地对象、跨实例读取、调试计数和 env-style override。
- 调整第 1 阶段接口测试，避免默认 `Memory()` 在单元测试中生成 `.memory/` 运行产物，并新增默认后端为 SQLite 的断言。

## 新增文件

- `memory/backends/__init__.py`
- `memory/backends/sqlite_store.py`
- `tests/test_memory_sqlite_store.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-02.md`

## 修改文件

- `memory/config.py`
- `memory/service.py`
- `tests/test_memory_interface.py`

## 公开接口

- `SQLiteMemoryStore(db_path: str)`
- `SQLiteMemoryStore.set_kv(key: str, value: object) -> None`
- `SQLiteMemoryStore.get_kv(key: str) -> object | None`
- `SQLiteMemoryStore.counts() -> DebugCounts`
- `Memory.store(key: str, value: object) -> None`
- `Memory.retrieve(key: str) -> object | None`
- `Memory.debug_counts() -> DebugCounts`
- `MemoryConfig.from_env(overrides: dict | None = None) -> MemoryConfig`

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_sqlite_store.py -v
```

RED 结果：

```text
4 failed, 1 passed in 0.06s
```

失败原因：

- `memory.backends.sqlite_store` 不存在。
- `Memory` 尚不能跨实例持久化。
- `MemoryConfig.from_env()` 尚不能识别 `MEMORY_BACKEND`、`MEMORY_DB_PATH` 这种环境变量风格覆盖参数。

GREEN 命令：

```bash
uv run pytest tests/test_memory_sqlite_store.py -v
```

GREEN 结果：

```text
5 passed in 0.04s
```

接口回归命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py -v
```

接口回归结果：

```text
9 passed in 0.04s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
64 passed in 0.20s
```

运行产物检查：

```bash
test ! -e .memory && echo 'no .memory residue' || find .memory -maxdepth 2 -type f -print
```

结果：

```text
no .memory residue
```

## 人工验证

步骤：

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

预期：

```text
[{'input': '我想去成都', 'response': '好的'}]
[{'input': '我想去成都', 'response': '好的'}]
```

实际结果：

```text
[{'input': '我想去成都', 'response': '好的'}]
[{'input': '我想去成都', 'response': '好的'}]
```

人工验证产生的 `.memory/manual.sqlite3` 已在验证后清理。

## SQLite 存储说明

SQLite 文件位置：

- 默认：`.memory/memory.sqlite3`
- 可通过 `MEMORY_DB_PATH` 或 `Memory(config={"MEMORY_DB_PATH": "..."})` 覆盖。

当前阶段创建的表：

- `memory_kv`

字段：

- `key`
- `value_json`
- `value_pickle`
- `value_type`
- `created_at`
- `updated_at`

值编码策略：

- JSON 可序列化值写入 `value_json`，`value_type="json"`。
- JSON 不可序列化的本地兼容对象写入 `value_pickle`，`value_type="pickle"`。
- pickle 仅用于本地兼容 KV 状态，不用于后续 semantic memory。

## 已知限制

- 当前阶段只持久化兼容 KV，不写入语义记忆记录。
- 当前阶段尚未实现审计日志和 outbox。
- 当前阶段尚未接入 Qdrant。
- 当前阶段尚未接入 BGE-M3。
- 当前阶段 `.memory/` 尚未加入 `.gitignore`，因为原计划把它放在第 9 阶段；本阶段测试已避免残留 `.memory/`，人工验证后也已清理。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段不会提交这些文件。

## 请求确认

请审阅本阶段结果，并确认是否进入第 3 阶段：审计日志和 Outbox。
