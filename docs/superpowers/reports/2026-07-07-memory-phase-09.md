# 第 9 阶段报告：现有 Agent 契约集成验证

## 本阶段目标

验证真实 `Memory` 实现替换原先兼容层后，现有 `Agent(context, memory)` 调用方式不需要修改；同时确认旅游业务常用 KV key 能通过 SQLite 持久化 round trip，并将 `.memory/` 加入 `.gitignore`。

## 本阶段改动

- 新增 `tests/test_memory_integration_with_agent_contract.py`。
- 修改根 `.gitignore`，加入 `.memory/`。
- 新增本阶段中文报告。

## 新增文件

- `tests/test_memory_integration_with_agent_contract.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-09.md`

## 修改文件

- `.gitignore`

## 是否改动非 memory 模块

本阶段没有修改以下运行模块：

- `agent.py`
- `context/`
- `skills/`
- `tools/`
- `models/`

唯一非 memory 代码改动是根 `.gitignore`，用于忽略 `.memory/` 本地运行产物。

## Agent 契约验证

验证入口：

- `Agent(context=context, memory=memory)`
- `agent.process_turn("你好")`
- `memory.retrieve("history")`

验证结论：

- `Agent` 仍然只依赖 `memory.store(key, value)` 和 `memory.retrieve(key)`。
- 真实 `Memory` 可以直接注入 `Agent`，不需要修改 `agent.py`。
- `process_turn()` 写入的 `history` 会持久化到 SQLite KV。

## 旅游业务 KV 验证

本阶段验证以下 key 可持久化 round trip：

- `current_requirement`
- `current_itinerary`
- `reset_flag`

验证结果：

- dict 可以按 JSON 形式持久化并恢复。
- `None` 可以持久化并恢复。
- bool 可以持久化并恢复。

## 自动验证

集成测试命令：

```bash
uv run pytest tests/test_memory_integration_with_agent_contract.py -v
```

结果：

```text
2 passed in 0.51s
```

说明：

- 本阶段测试首次运行即通过，因为前 1-8 阶段已经保持了 `store/retrieve` 兼容契约。

全量测试命令：

```bash
uv run pytest -v
```

全量测试结果：

```text
92 passed in 0.68s
```

## REPL 人工验证

执行命令：

```bash
printf '我想去成都\n玩3天\n预算3000元\nquit\n' | uv run python loop.py
```

实际输出：

```text
Agent is ready. Type 'exit' or 'quit' to stop.
> [tongyi] API Key 配置异常，请检查 .env
> [tongyi] API Key 配置异常，请检查 .env
> [tongyi] API Key 配置异常，请检查 .env
> Goodbye.
```

说明：

- REPL 可以正常启动。
- 三轮输入都完成处理，没有因为真实 `Memory` 崩溃。
- 当前回复内容来自模型层的 Tongyi API key 配置异常，不是 memory 层错误。

读取验证命令：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
print(m.retrieve("history"))
print(m.debug_counts())
PY
```

实际输出：

```text
[{'input': '我想去成都', 'response': '[tongyi] API Key 配置异常，请检查 .env'}, {'input': '玩3天', 'response': '[tongyi] API Key 配置异常，请检查 .env'}, {'input': '预算3000元', 'response': '[tongyi] API Key 配置异常，请检查 .env'}]
kv=1 records=0 sources=0 outbox=3 audit=6 summaries=0
```

说明：

- `history` 已经写入 `.memory/memory.sqlite3`。
- `kv=1` 表示历史记录 key 已持久化。
- `outbox=3` 表示三轮输入生成了三条语义候选 outbox。
- `audit=6` 表示三次 KV 写入审计 + 三次 outbox 入队审计。

## 已知限制

- REPL 验证受当前模型 API key 配置影响，输出为 Tongyi key 配置错误；memory 持久化仍正常。
- `.memory/` 已加入 `.gitignore`，本地 SQLite 运行产物不会进入 git。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 后续阶段

剩余工作是最终收尾检查和总功能回报。
