# Memory 层企业级实现总功能回报

## 交付范围

本次交付按工程阶段完成企业级 Memory 层，从兼容 KV 到 SQLite 持久化、审计/outbox、脱敏/分类、BGE-M3 embedding、Qdrant 向量索引、语义记忆闭环、Summary/Import/Export，以及现有 Agent 契约集成验证。

实现过程遵循：

- 每阶段先写测试，再实现功能。
- 每阶段运行阶段测试、回归测试、全量测试。
- 每阶段写中文报告并单独提交。
- 不修改 `agent.py`、`context/`、`skills/`、`tools/`、`models/` 的业务运行逻辑。

## 阶段 Commit 列表

- `1c09b75` `docs(memory): add enterprise memory layer design`
- `f5c62a2` `docs(memory): require Chinese plans and reports`
- `399f879` `docs(memory): add staged enterprise memory implementation plan`
- `b084776` `feat(memory): add configuration and public interface`
- `13b09c1` `feat(memory): persist compatibility state in sqlite`
- `14a38a7` `feat(memory): add audit log and semantic outbox`
- `c9ce398` `feat(memory): add redaction and candidate classification`
- `660f0d1` `feat(memory): add bge-m3 embedding provider`
- `417667c` `feat(memory): add qdrant vector index backend`
- `4f2caa6` `feat(memory): add semantic remember search and forget`
- `5788577` `feat(memory): add summary import and export`
- `c0f36eb` `test(memory): verify agent contract integration`

## 阶段报告路径

- `docs/superpowers/reports/2026-07-07-memory-phase-01.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-02.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-03.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-04.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-05.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-06.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-07.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-08.md`
- `docs/superpowers/reports/2026-07-07-memory-phase-09.md`

## 最终公开接口

兼容 KV：

- `Memory.store(key: str, value: object) -> None`
- `Memory.retrieve(key: str) -> object | None`
- `Memory.debug_counts() -> DebugCounts`

语义记忆：

- `Memory.remember(content, kind, scope, metadata, source) -> str`
- `Memory.search(query, top_k, scope, project_id, include_sources) -> list[MemorySearchResult]`
- `Memory.forget(memory_id, reason) -> bool`

Summary / Import / Export：

- `Memory.get_summary(scope: str = "project") -> str`
- `Memory.update_summary(summary: str, scope: str = "project") -> None`
- `Memory.export(format: str = "markdown") -> str`
- `Memory.import_memories(content: str, source: str = "manual") -> list[str]`

Embedding：

- `FakeEmbeddingProvider.embed(text: str) -> list[float]`
- `BGEM3EmbeddingProvider.embed(text: str) -> list[float]`

Qdrant：

- `QdrantMemoryIndex.ensure_collection() -> None`
- `QdrantMemoryIndex.upsert_memory(record, vector) -> None`
- `QdrantMemoryIndex.search(vector, filters, top_k) -> list[dict]`
- `QdrantMemoryIndex.delete_memory(memory_id: str) -> None`

SQLite 内部接口：

- `SQLiteMemoryStore.set_kv()`
- `SQLiteMemoryStore.get_kv()`
- `SQLiteMemoryStore.append_audit()`
- `SQLiteMemoryStore.enqueue_outbox()`
- `SQLiteMemoryStore.list_outbox()`
- `SQLiteMemoryStore.insert_source()`
- `SQLiteMemoryStore.insert_record()`
- `SQLiteMemoryStore.get_record()`
- `SQLiteMemoryStore.list_records()`
- `SQLiteMemoryStore.mark_deleted()`
- `SQLiteMemoryStore.upsert_summary()`
- `SQLiteMemoryStore.get_summary()`
- `SQLiteMemoryStore.list_active_records()`

## 存储分层

- SQLite KV：保存兼容状态，例如 `history`、`current_requirement`、`current_itinerary`、`reset_flag`。
- SQLite records/sources：保存 durable memory 正文、metadata、source、status、scope、kind。
- SQLite audit：保存写入、outbox、forget 等审计事件。
- SQLite outbox：保存从 `history` 生成的待处理语义记忆候选事件。
- SQLite summaries：保存 project/user scoped summary。
- Qdrant：保存语义记忆向量和 filter payload。

## 验证结果

最终阶段验证命令：

```bash
uv run pytest -v
```

结果：

```text
92 passed
```

REPL 验证：

- `loop.py` 可以正常启动。
- 三轮输入不会因为真实 `Memory` 崩溃。
- `history` 已写入 `.memory/memory.sqlite3`。
- 当前回复为 Tongyi API key 配置提示，属于模型配置问题，不是 memory 层错误。

Qdrant 验证：

- 本地 `http://localhost:6333/collections` 可访问。
- 返回 JSON 中包含已有 collections。

## 用户人工验证入口

兼容 KV：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
m.store("current_requirement", {"destination": "成都", "days": 3})
print(m.retrieve("current_requirement"))
print(m.debug_counts())
PY
```

Summary：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory()
m.update_summary("用户正在构建企业级本地记忆系统。")
print(m.get_summary())
print(m.export("markdown")[:300])
PY
```

真实 BGE-M3：

```bash
uv run python - <<'PY'
from memory.embeddings import BGEM3EmbeddingProvider
p = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")
v = p.embed("我喜欢安静的酒店")
print(len(v))
print(type(v[0]).__name__)
PY
```

Qdrant 服务：

```bash
curl -s http://localhost:6333/collections
```

## 已知限制

- 真实 BGE-M3 大模型端到端写入没有作为自动测试执行；自动测试使用 fake embedding provider。
- 真实 Qdrant 写入由后端接口和 fake client 测试覆盖；本地 Qdrant HTTP 已做只读烟测。
- `include_sources=True` 参数已保留，但 `search()` 当前暂未回填完整 `SourceRef`。
- outbox 目前只入队候选事件，还没有后台 worker 自动消费并调用 `remember()`。
- Markdown import 是简单 bullet parser，不是完整 Markdown parser。
- JSONL import 会重新生成 memory/source ID。
- 当前 REPL 输出受模型 API key 配置影响。

## 下一步建议

- 增加 outbox worker：对候选事件执行脱敏、分类、embedding、Qdrant upsert。
- 给 `search(include_sources=True)` 增加 source 回填。
- 给 export/import 增加 tenant/project/scope 过滤参数。
- 增加真实 BGE-M3 + Qdrant 的可选慢速集成测试标记，例如 `pytest -m integration`。
- 增加记忆治理 API：审计查询、恢复 deleted、TTL 过期清理。
