# 第 3 阶段报告：审计日志和 Outbox

## 本阶段目标

在 SQLite 兼容 KV 存储之上增加企业级可观测性：每次 `Memory.store()` 写入都产生审计日志；当写入 `history` 时，生成可去重的语义记忆候选 outbox 事件，为后续脱敏、分类、embedding 和 Qdrant 写入做准备。

## 本阶段改动

- 新增 `memory/audit.py`，集中定义审计动作常量和默认 actor。
- 扩展 SQLite schema，新增 `memory_audit_log` 和 `memory_outbox` 两张表。
- 新增 `SQLiteMemoryStore.append_audit()`，用于写入审计日志。
- 新增 `SQLiteMemoryStore.enqueue_outbox()`，用于写入待处理记忆事件。
- 新增 `SQLiteMemoryStore.list_outbox()`，用于检查 outbox 内容。
- 新增 `SQLiteMemoryStore.history_turn_dedupe_key()`，用于对同一条 history turn 去重。
- 修改 `Memory.store()`：
  - SQLite 分支每次写 KV 后写入 `memory.kv.stored` 审计日志。
  - 当 key 为 `history` 且 `generate_memories=True` 时，为每条 history turn 生成 `memory.semantic_candidate.created` outbox 事件。
  - 如果重复写入同一条 history turn，outbox 根据 dedupe key 去重。
  - 如果 `MEMORY_GENERATE_MEMORIES=false`，只写 KV 和审计，不生成 outbox。

## 新增文件

- `memory/audit.py`
- `tests/test_memory_audit_outbox.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-03.md`

## 修改文件

- `memory/backends/sqlite_store.py`
- `memory/service.py`

## 公开接口

- `SQLiteMemoryStore.append_audit(actor: str, action: str, target_id: str, payload: dict) -> str`
- `SQLiteMemoryStore.enqueue_outbox(event_type: str, payload: dict, dedupe_key: str | None = None) -> str | None`
- `SQLiteMemoryStore.list_outbox(status: str | None = None) -> list[dict]`
- `SQLiteMemoryStore.history_turn_dedupe_key(turn: object) -> str`
- `Memory.store(key: str, value: object) -> None`
- `Memory.debug_counts() -> DebugCounts`

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_audit_outbox.py -v
```

RED 结果：

```text
5 failed in 0.05s
```

失败原因：

- `store()` 尚未写入 audit。
- `history` 尚未生成 outbox。
- `SQLiteMemoryStore.enqueue_outbox()` 不存在。

GREEN 命令：

```bash
uv run pytest tests/test_memory_audit_outbox.py -v
```

GREEN 结果：

```text
5 passed in 0.04s
```

回归测试命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py -v
```

回归测试结果：

```text
14 passed in 0.06s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
69 passed in 0.29s
```

运行产物检查命令：

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
m.store("history", [{"input": "喜欢安静酒店", "response": "已记录"}])
print(m.debug_counts())
PY
```

预期：

```text
kv=1 records=0 sources=0 outbox=1 audit=2 summaries=0
```

实际：

```text
kv=1 records=0 sources=0 outbox=1 audit=2 summaries=0
```

说明：

- `kv=1`：写入了一个 `history` key。
- `outbox=1`：生成了一条 `memory.semantic_candidate.created` 事件。
- `audit=2`：一次 KV 写入审计 + 一次 outbox 入队审计。

人工验证产生的 `.memory/manual.sqlite3` 已在验证后清理。

## 已知限制

- 当前阶段 outbox 只负责保存“待处理语义记忆候选事件”，还不会真正做脱敏、分类、embedding 或写入 Qdrant。
- 当前阶段 audit 只是 SQLite 表记录，还没有导出、查询接口或用户界面。
- 当前阶段 `history` outbox 去重按完整 turn 内容计算 hash；如果同一输入但回复不同，会被视为不同事件。
- 当前阶段 `.memory/` 仍未加入 `.gitignore`，本阶段测试和人工验证都已避免留下 `.memory/` 运行产物。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 请求确认

请审阅本阶段结果，并确认是否进入第 4 阶段：脱敏和记忆候选分类。
