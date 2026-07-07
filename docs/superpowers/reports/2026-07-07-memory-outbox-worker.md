# Outbox 自动 Worker 实现报告

## 本次目标

把 `memory_outbox` 中的 pending 候选事件自动处理成长期记忆，打通：

```text
history
-> memory_outbox.pending
-> process_outbox worker
-> redact_text
-> candidate_extractor
-> Memory.remember
-> SQLite memory_records / memory_sources
-> Qdrant vector
-> memory_outbox.processed / skipped / failed
```

## 新增接口

- `Memory.process_outbox(limit: int = 10) -> dict`
- `MemoryOutboxWorker.process_pending(limit: int = 10) -> dict`
- `SQLiteMemoryStore.update_outbox_status(...) -> bool`

## 状态流转

- `pending`：等待 worker 处理。
- `processed`：已经转成长期记忆，并在 payload 中写入 `worker_result.memory_id`。
- `skipped`：分类后认为不值得记，不写入 `memory_records`。
- `failed`：处理失败，记录 `last_error` 和 `worker_result.error`。

## 实现位置

- Worker：`memory/worker.py`
- Memory 门面：`memory/service.py`
- Outbox 状态更新：`memory/backends/sqlite_store.py`
- Qdrant point id 修复：`memory/backends/qdrant_store.py`

## 自动测试

新增测试：

- `tests/test_memory_outbox_worker.py`

覆盖：

- semantic/procedural 候选自动转成长期记忆。
- 低价值候选自动 skipped。
- 处理失败自动 failed。
- `limit` 限制只处理指定数量。

同步更新：

- `tests/test_memory_full_data_flow.py`
  - 原来的“手动模拟消费 outbox”改成真实 `Memory.process_outbox()`。
- `tests/test_memory_qdrant_store.py`
  - 增加真实 Qdrant point id 约束：业务 `mem_xxx` 会映射为稳定 UUID point id。

## 验证结果

Worker 测试：

```bash
uv run pytest tests/test_memory_outbox_worker.py -v
```

结果：

```text
4 passed
```

Worker + Qdrant + 数据流测试：

```bash
uv run pytest tests/test_memory_outbox_worker.py tests/test_memory_qdrant_store.py tests/test_memory_full_data_flow.py -v
```

结果：

```text
17 passed
```

全量测试：

```bash
uv run pytest -q
```

结果：

```text
105 passed
```

真实 Qdrant point id 烟测：

```text
写入成功，查询返回 payload 中的 memory_id=mem_worker_smoke，随后删除成功。
```

真实 SQLite + 真实 Qdrant Worker 烟测：

```text
before kv=1 records=0 sources=0 outbox=3 audit=4 summaries=0
worker {'processed': 2, 'skipped': 1, 'failed': 0, 'remembered_ids': ['mem_...', 'mem_...']}
after kv=1 records=2 sources=2 outbox=3 audit=9 summaries=0
search [('semantic', 'Q: 用户喜欢安静酒店\nA: 已记录'), ('procedural', 'Q: 以后每一步都写中文阶段报告\nA: 收到')]
outbox [('processed', 'semantic'), ('processed', 'procedural'), ('skipped', 'episodic')]
qdrant_count 2
```

## 人工验证命令

下面命令会使用 `.memory/manual_worker.sqlite3`，方便你人工查看 SQLite 表：

```bash
rm -f .memory/manual_worker.sqlite3
uv run python - <<'PY'
from memory import Memory

m = Memory(config={"MEMORY_DB_PATH": ".memory/manual_worker.sqlite3"})
m.store("history", [
    {"input": "用户喜欢安静酒店", "response": "已记录"},
    {"input": "以后每一步都写中文阶段报告", "response": "收到"},
    {"input": "好的", "response": ""},
])
print("before", m.debug_counts())
print("worker", m.process_outbox(limit=10))
print("after", m.debug_counts())
PY
```

如果你只想验证“SQLite + Qdrant 是否真的落库”，但不想等待 BGE-M3 模型加载，可以用这个快速版。它仍然会写真实 Qdrant，只是向量由测试 embedding 生成：

```bash
rm -f .memory/manual_worker.sqlite3
uv run python - <<'PY'
from qdrant_client import QdrantClient
from memory import Memory
from memory.backends.qdrant_store import QdrantMemoryIndex
from memory.embeddings import FakeEmbeddingProvider

collection = "agent_memories_manual_worker"
client = QdrantClient(url="http://localhost:6333")
if client.collection_exists(collection):
    client.delete_collection(collection)

m = Memory(
    config={
        "MEMORY_DB_PATH": ".memory/manual_worker.sqlite3",
        "QDRANT_COLLECTION": collection,
    },
    embedding_provider=FakeEmbeddingProvider(),
    vector_index=QdrantMemoryIndex(client=client, collection_name=collection, vector_size=1024),
)
m.store("history", [
    {"input": "用户喜欢安静酒店", "response": "已记录"},
    {"input": "以后每一步都写中文阶段报告", "response": "收到"},
    {"input": "好的", "response": ""},
])
print("before/after worker", m.process_outbox(limit=10), m.debug_counts())
print("search", [(r.kind.value, r.content) for r in m.search("安静酒店 中文报告", top_k=5)])
print("qdrant_count", client.count(collection_name=collection, exact=True).count)
PY
```

查看 outbox 状态：

```bash
sqlite3 .memory/manual_worker.sqlite3 \
"select status, json_extract(payload_json, '$.worker_result.kind'), json_extract(payload_json, '$.worker_result.reason') from memory_outbox order by created_at;"
```

预期能看到：

```text
processed|semantic|命中稳定偏好或项目事实
processed|procedural|命中流程或工作方式偏好
skipped|episodic|未命中稳定记忆规则
```

查看真正落库的长期记忆：

```bash
sqlite3 .memory/manual_worker.sqlite3 \
"select kind, content, status from memory_records order by created_at;"
```

预期能看到：

```text
semantic|Q: 用户喜欢安静酒店...
procedural|Q: 以后每一步都写中文阶段报告...
```

查看来源表：

```bash
sqlite3 .memory/manual_worker.sqlite3 \
"select source_type, source_ref, excerpt from memory_sources order by created_at;"
```

预期：

```text
source_type 为 outbox，source_ref 是对应 outbox event_id。
```

查看计数：

```bash
uv run python - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual_worker.sqlite3"})
print(m.debug_counts())
PY
```

预期：

```text
kv=1 records=2 sources=2 outbox=3 audit=9 summaries=0
```

## 注意

- 这次也修复了真实 Qdrant 不接受 `mem_xxx` point id 的问题。现在 Qdrant point id 使用稳定 UUID，业务 `memory_id` 仍保存在 payload 中。
- 默认真实运行会使用 BGE-M3 和 Qdrant；如果本地模型加载慢，这是正常现象。
