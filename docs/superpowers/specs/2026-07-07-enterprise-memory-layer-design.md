# Enterprise Memory Layer Design

## 1. Goal

Implement only the `memory/` layer for the current modular agent project, using Path A: a local enterprise-grade memory system built on SQLite, Qdrant, and BGE-M3.

The implementation must stay compatible with the existing `Memory.store(key, value)` and `Memory.retrieve(key)` contract used by `loop.py`, `agent.py`, and `skills/`. New enterprise memory capabilities will be additive.

The work must be delivered in small, inspectable engineering steps. Each step must end with a report, automatic verification evidence, exact file/interface locations, and manual verification instructions. No later step may begin until the user approves the previous step.

All implementation plans, phase reports, manual verification instructions, and delivery summaries must be written in Chinese. Code identifiers, command names, file paths, environment variable names, and public API names remain in English.

## 2. Current Project Context

Current memory state:

- `memory/` only contains `.gitkeep`.
- `loop.py` imports `Memory` from `memory`; if import fails, it falls back to an in-memory stub.
- Existing consumers expect:
  - `Memory.store(key, value) -> None`
  - `Memory.retrieve(key) -> Any | None`
- Existing keys used by the app:
  - `history`
  - `current_requirement`
  - `current_itinerary`
  - `reset_flag`

Related module boundary from the existing context design:

- `Context` is the short-lived active view.
- `Memory` is the long-lived, persistent store.
- `Skill` reads Memory for past facts and state.
- This project must not move Context compression logic into Memory.

## 3. Product Patterns To Emulate

### 3.1 Codex-Inspired Behavior

Codex Memories are treated as an optional recall layer rather than mandatory source of truth. They carry stable preferences, recurring workflows, tech stacks, project conventions, and known pitfalls across threads. Required team rules belong in checked-in documentation such as `AGENTS.md`, not only in memory.

Codex also distinguishes:

- global enablement
- per-thread use/generation controls
- generated local memory files
- summaries, durable entries, recent inputs, and supporting evidence
- background memory generation instead of immediate synchronous generation after every thread
- secret redaction

Source: https://developers.openai.com/codex/memories

### 3.2 Claude-Inspired Behavior

Claude's memory model emphasizes user visibility and control:

- users can view and edit what the assistant remembers
- memories can be updated from chat
- memory use can be disabled
- referenced memories can cite prior chats
- organizations can disable memory centrally
- projects have separate memory summaries
- memory import/export is supported

Sources:

- https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context
- https://support.claude.com/en/articles/9519177-how-can-i-create-and-manage-projects
- https://support.claude.com/en/articles/12123587-import-and-export-your-memory-from-claude

## 4. Technical Foundation

### 4.1 Qdrant

Qdrant stores vectors as points with JSON payloads. A collection contains vectors with consistent dimensionality and distance metric. Payload filters allow semantic search to be constrained by structured metadata such as tenant, user, project, scope, kind, and status.

Sources:

- https://qdrant.tech/documentation/manage-data/collections/
- https://qdrant.tech/documentation/quickstart/

### 4.2 BGE-M3

BGE-M3 supports multilingual dense retrieval, sparse retrieval, and multi-vector retrieval. For this project, Phase 1 of semantic memory will use dense embeddings only. BGE-M3 dense vectors are 1024-dimensional and support long text up to 8192 tokens.

Source: https://huggingface.co/BAAI/bge-m3

## 5. Recommended Architecture: Path A

Use a local enterprise-grade implementation with distributed-system interfaces:

- SQLite is the local authoritative metadata and compatibility store.
- Qdrant is the semantic vector index.
- BGE-M3 is the local embedding model.
- Outbox tables model future async worker behavior without requiring Kafka now.
- Interfaces are shaped so SQLite can later be replaced by Postgres, local outbox by Kafka/Redpanda, and local BGE-M3 by an embedding service.

This gives the user a working local system now, without painting the project into a corner.

## 6. Non-Goals

This work must not:

- modify `agent.py` prompt injection behavior unless a later approved step explicitly asks for it
- modify `context/` compaction behavior
- add a web UI
- require Redis, Kafka, Postgres, or a Qdrant cluster in the first implementation
- store secrets or raw credentials in durable semantic memory
- silently use memories across projects without scope filters

## 7. Memory Types

The memory layer will support these memory kinds:

| Kind | Purpose | Example |
| --- | --- | --- |
| `kv_state` | Compatibility state for current app keys | `history`, `current_requirement` |
| `episodic` | Event-level memory from turns or tool results | "User asked for Chengdu itinerary" |
| `semantic` | Durable fact or preference | "User prefers Chinese explanations" |
| `procedural` | Stable workflow preference | "Run tests after each module step" |
| `summary` | User/project memory summary | Claude-style editable summary |
| `tombstone` | Deletion marker | Prevents accidental rehydration |

## 8. Scope Model

Every enterprise memory record must carry a scope:

- `tenant_id`: default `local`
- `user_id`: default `default`
- `project_id`: default derived from repo name, `lazyaiX-agent-corp-1`
- `thread_id`: optional
- `scope`: one of `global`, `user`, `project`, `thread`

Default recall policy:

- use current `tenant_id`
- use current `user_id`
- prefer current `project_id`
- do not cross projects unless explicitly requested by API parameter
- never return deleted or expired records

## 9. Public Interfaces

### 9.1 Compatibility Interface

These methods must exist first and remain stable:

```python
class Memory:
    def store(self, key: str, value: object) -> None: ...
    def retrieve(self, key: str) -> object | None: ...
```

Compatibility behavior:

- `store("history", value)` persists the exact Python value when serializable.
- `retrieve("history")` returns the same shape currently expected by `agent.py`.
- Unsupported object values are preserved using safe local serialization only after tests prove current `Itinerary` objects round-trip.
- If a stored object cannot be serialized to JSON, the SQLite implementation may use pickle for local-only compatibility state, but semantic memory must store text and metadata, not arbitrary pickle blobs.

### 9.2 Enterprise Interface

These methods are additive and must be implemented only after compatibility persistence is tested:

```python
class Memory:
    def remember(
        self,
        content: str,
        *,
        kind: str = "semantic",
        scope: str = "project",
        metadata: dict | None = None,
        source: dict | None = None,
    ) -> str: ...

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: str | None = None,
        project_id: str | None = None,
        include_sources: bool = True,
    ) -> list[object]: ...

    def forget(self, memory_id: str, *, reason: str = "") -> bool: ...
    def get_summary(self, *, scope: str = "project") -> str: ...
    def update_summary(self, summary: str, *, scope: str = "project") -> None: ...
    def export(self, format: str = "markdown") -> str: ...
    def import_memories(self, content: str, *, source: str = "manual") -> list[str]: ...
```

The implementation plan must replace `object` return types with concrete Pydantic model classes before writing code.

## 10. Data Storage Design

### 10.1 SQLite Tables

The implementation plan must create migrations or schema bootstrap for:

- `memory_kv`
  - key
  - value_json
  - value_pickle
  - value_type
  - created_at
  - updated_at

- `memory_records`
  - memory_id
  - tenant_id
  - user_id
  - project_id
  - thread_id
  - scope
  - kind
  - content
  - metadata_json
  - status
  - confidence
  - importance
  - sensitivity
  - source_id
  - created_at
  - updated_at
  - expires_at

- `memory_sources`
  - source_id
  - source_type
  - source_ref
  - excerpt
  - metadata_json
  - created_at

- `memory_outbox`
  - event_id
  - event_type
  - payload_json
  - status
  - attempts
  - last_error
  - created_at
  - updated_at

- `memory_audit_log`
  - audit_id
  - actor
  - action
  - target_id
  - payload_json
  - created_at

- `memory_summaries`
  - summary_id
  - tenant_id
  - user_id
  - project_id
  - scope
  - content
  - version
  - created_at
  - updated_at

### 10.2 Qdrant Collection

Collection:

- name: `agent_memories_v1`
- vector size: `1024`
- distance: `Cosine`

Payload:

- `memory_id`
- `tenant_id`
- `user_id`
- `project_id`
- `thread_id`
- `scope`
- `kind`
- `status`
- `confidence`
- `importance`
- `sensitivity`
- `source_id`
- `created_at`
- `updated_at`
- `expires_at`

## 11. Write Flow

### 11.1 Compatibility Write

When code calls `store(key, value)`:

1. Persist the key and value in SQLite.
2. Write an audit event.
3. If `key == "history"`, detect newly appended turns and add outbox events for semantic processing.
4. Return immediately after local persistence.

### 11.2 Semantic Write

When code calls `remember(content, ...)` or when an outbox event is processed:

1. Redact sensitive values.
2. Classify the memory kind and durability.
3. Store source evidence.
4. Store the memory record in SQLite.
5. Generate a BGE-M3 dense embedding.
6. Upsert the vector and payload into Qdrant.
7. Write an audit event.

## 12. Recall Flow

When code calls `search(query, ...)`:

1. Check policy flags for memory use.
2. Embed the query with BGE-M3.
3. Query Qdrant using payload filters.
4. Fetch matching metadata and content from SQLite.
5. Drop deleted, expired, or cross-scope records.
6. Rerank by vector score, recency, confidence, and importance.
7. Return structured results with source evidence.

## 13. Forget Flow

When code calls `forget(memory_id, reason)`:

1. Mark SQLite record as deleted.
2. Delete or tombstone the Qdrant point.
3. Insert a `tombstone` record so later background processing does not recreate the memory.
4. Write audit log.
5. Return whether a record was changed.

## 14. Import And Export

Export must support:

- Markdown for human review
- JSONL for backup/migration

Markdown export structure:

```markdown
# Memory Export

## Summary

...

## Durable Memories

- [memory_id] content
  - kind:
  - scope:
  - source:

## Deleted Memories

...
```

Import must:

- parse Markdown or JSONL
- create source records with `source="manual_import"`
- run redaction before persistence
- return created memory ids

## 15. Privacy, Governance, And Policy

Environment/config policy:

- `ENABLE_MEMORY=true`
- `MEMORY_USE_MEMORIES=true`
- `MEMORY_GENERATE_MEMORIES=true`
- `MEMORY_DISABLE_ON_EXTERNAL_CONTEXT=true`
- `MEMORY_REDACT_SECRETS=true`
- `MEMORY_TENANT_ID=local`
- `MEMORY_USER_ID=default`
- `MEMORY_PROJECT_ID=lazyaiX-agent-corp-1`
- `MEMORY_DB_PATH=.memory/memory.sqlite3`
- `QDRANT_URL=http://localhost:6333`
- `QDRANT_COLLECTION=agent_memories_v1`
- `MEMORY_EMBEDDING_MODEL=BAAI/bge-m3`

Policy behavior:

- If `MEMORY_USE_MEMORIES=false`, `search()` returns no records.
- If `MEMORY_GENERATE_MEMORIES=false`, `store()` still persists KV but creates no semantic outbox records.
- If redaction is enabled, durable semantic memory must not store obvious API keys, bearer tokens, cookies, or private keys.
- If external context was used and `MEMORY_DISABLE_ON_EXTERNAL_CONTEXT=true`, automatic semantic generation is skipped for that event.

## 16. Engineering Delivery Process

Implementation must be broken into controlled phases. Each phase must:

1. state the goal
2. list exact files created or modified
3. list exact interfaces added or changed
4. include automated tests
5. run automated verification
6. provide manual verification steps
7. produce a written phase report
8. wait for user approval before the next phase

The agent must not batch multiple phases into one opaque implementation.

All phase output must be written in Chinese, including the implementation plan, phase reports, verification notes, approval requests, and known limitation summaries.

## 17. Phase Plan

### Phase 0: Spec And Plan Only

Deliverables:

- design spec
- implementation plan
- no runtime code

Manual verification:

- user reads design and implementation plan
- user confirms phase boundaries and acceptance criteria

### Phase 1: Configuration And Public Interfaces

Goal:

Create the `memory/` module shape without connecting SQLite, Qdrant, or BGE-M3 yet.

Expected files:

- `memory/__init__.py`
- `memory/config.py`
- `memory/models.py`
- `memory/service.py`
- `tests/test_memory_interface.py`

Expected interfaces:

- `Memory.store`
- `Memory.retrieve`
- config loader
- Pydantic model skeletons

Automatic verification:

- interface import test
- compatibility method existence test
- default config test

Manual verification:

```bash
python3 - <<'PY'
from memory import Memory
m = Memory()
m.store("hello", {"world": 1})
print(m.retrieve("hello"))
PY
```

Expected output:

```text
{'world': 1}
```

Phase report must answer:

- Which files define the public API?
- Which methods are stable for existing callers?
- Which components are intentionally interface-only and not connected yet?

### Phase 2: SQLite Compatibility Store

Goal:

Make existing `store/retrieve` persistent across process restarts.

Expected files:

- `memory/backends/sqlite_store.py`
- `memory/service.py`
- `tests/test_memory_sqlite_store.py`

Expected interfaces:

- `SQLiteMemoryStore.set_kv(key, value)`
- `SQLiteMemoryStore.get_kv(key)`

Automatic verification:

- JSON value round-trip
- non-JSON local object round-trip if needed by current `Itinerary`
- restart persistence test using a temporary database
- `history` shape compatibility test

Manual verification:

```bash
python3 - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual.sqlite3"})
m.store("history", [{"input": "我想去成都", "response": "好的"}])
print(m.retrieve("history"))
PY

python3 - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual.sqlite3"})
print(m.retrieve("history"))
PY
```

Expected output in both runs:

```text
[{'input': '我想去成都', 'response': '好的'}]
```

Phase report must answer:

- Where is the SQLite file?
- Which table stores compatibility keys?
- How does it handle non-JSON values?

### Phase 3: Audit Log And Outbox

Goal:

Add enterprise observability without semantic search yet.

Expected files:

- `memory/audit.py`
- `memory/backends/sqlite_store.py`
- `memory/service.py`
- `tests/test_memory_audit_outbox.py`

Expected interfaces:

- `SQLiteMemoryStore.append_audit(...)`
- `SQLiteMemoryStore.enqueue_outbox(...)`
- `SQLiteMemoryStore.list_outbox(...)`

Automatic verification:

- `store()` creates audit log
- `store("history", appended_history)` creates semantic outbox event
- duplicate history entries do not create duplicate outbox events

Manual verification:

```bash
python3 - <<'PY'
from memory import Memory
m = Memory(config={"MEMORY_DB_PATH": ".memory/manual.sqlite3"})
m.store("history", [{"input": "喜欢安静酒店", "response": "已记录"}])
print(m.debug_counts())
PY
```

Expected output includes non-zero audit count and outbox count.

Phase report must answer:

- Which actions are audited?
- What outbox event types exist?
- How can the user inspect counts manually?

### Phase 4: Redaction And Memory Classification

Goal:

Prevent secrets from entering durable semantic memory and classify useful records.

Expected files:

- `memory/redaction.py`
- `memory/classifier.py`
- `tests/test_memory_redaction_classifier.py`

Expected interfaces:

- `redact_text(text: str) -> RedactionResult`
- `classify_memory_candidate(text: str) -> MemoryClassification`

Automatic verification:

- API key redaction
- bearer token redaction
- cookie/private-key redaction
- stable preference classified as durable
- one-off low-value chat skipped

Manual verification:

```bash
python3 - <<'PY'
from memory.redaction import redact_text
print(redact_text("token=sk-abcdef1234567890").text)
PY
```

Expected output contains a redaction marker instead of the raw secret.

Phase report must answer:

- Which sensitive patterns are redacted?
- Which memory candidates are skipped?
- Where can classification rules be reviewed?

### Phase 5: BGE-M3 Embedding Provider

Goal:

Add local embedding generation behind an interface, with tests that can run without loading the full model.

Expected files:

- `memory/embeddings.py`
- `tests/test_memory_embeddings.py`

Expected interfaces:

- `EmbeddingProvider.embed(text: str) -> list[float]`
- `BGEM3EmbeddingProvider.embed(text: str) -> list[float]`
- `FakeEmbeddingProvider` for tests

Automatic verification:

- fake provider returns deterministic 1024-dimensional vector
- BGE provider is import-safe when dependency is missing
- model loading is lazy

Manual verification:

```bash
python3 - <<'PY'
from memory.embeddings import BGEM3EmbeddingProvider
p = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")
v = p.embed("我喜欢安静的酒店")
print(len(v))
print(round(sum(v[:5]), 6))
PY
```

Expected output:

```text
1024
<some numeric value>
```

Phase report must answer:

- Which embedding model is configured?
- When is the model loaded?
- How can the user verify vector dimension?

### Phase 6: Qdrant Vector Store

Goal:

Create collection management and vector upsert/search with fake embeddings first.

Expected files:

- `memory/backends/qdrant_store.py`
- `tests/test_memory_qdrant_store.py`

Expected interfaces:

- `QdrantMemoryIndex.ensure_collection()`
- `QdrantMemoryIndex.upsert_memory(record, vector)`
- `QdrantMemoryIndex.search(vector, filters, top_k)`
- `QdrantMemoryIndex.delete_memory(memory_id)`

Automatic verification:

- collection creation uses vector size 1024 and cosine distance
- payload filters include tenant/user/project/status
- upsert/search works against local or mocked Qdrant client

Manual verification:

```bash
curl -s http://localhost:6333/collections | head
```

Then run the project-provided Qdrant smoke test command from the phase report.

Phase report must answer:

- What collection name was created?
- What payload fields are indexed or filtered?
- How can the user verify records in Qdrant?

### Phase 7: `remember`, `search`, And `forget`

Goal:

Connect SQLite records, BGE-M3 embeddings, and Qdrant search into the enterprise API.

Expected files:

- `memory/service.py`
- `memory/retrieval.py`
- `tests/test_memory_service_semantic.py`

Expected interfaces:

- `Memory.remember(...) -> str`
- `Memory.search(...) -> list[MemorySearchResult]`
- `Memory.forget(...) -> bool`

Automatic verification:

- `remember()` creates SQLite record and Qdrant point
- `search()` returns scoped result with source
- `forget()` removes search visibility and writes tombstone/audit
- cross-project memories are filtered out by default

Manual verification:

```bash
python3 - <<'PY'
from memory import Memory
m = Memory()
mid = m.remember("用户喜欢安静、交通方便的酒店", kind="semantic")
print("id", mid)
print([r.content for r in m.search("住宿偏好", top_k=3)])
m.forget(mid, reason="manual test")
print(m.search("住宿偏好", top_k=3))
PY
```

Expected behavior:

- first search returns the hotel preference
- after `forget`, the deleted memory is absent

Phase report must answer:

- Where is each semantic memory stored?
- How does search filter scope?
- How does deletion prevent reappearance?

### Phase 8: Summary, Import, And Export

Goal:

Add Claude-style visible/editable memory summaries and backup/migration.

Expected files:

- `memory/exporter.py`
- `memory/service.py`
- `tests/test_memory_import_export_summary.py`

Expected interfaces:

- `Memory.get_summary(...)`
- `Memory.update_summary(...)`
- `Memory.export(format="markdown" | "jsonl")`
- `Memory.import_memories(content, source="manual")`

Automatic verification:

- summary round-trip
- markdown export includes summary, durable memories, sources, deleted entries
- jsonl export/import round-trip

Manual verification:

```bash
python3 - <<'PY'
from memory import Memory
m = Memory()
m.update_summary("用户正在构建企业级本地记忆系统。")
print(m.get_summary())
print(m.export("markdown")[:500])
PY
```

Expected output includes the summary and markdown sections.

Phase report must answer:

- How can the user see all remembered content?
- How can the user edit a summary?
- How can memories be backed up?

### Phase 9: End-To-End Memory Layer Integration

Goal:

Verify the memory layer works under the existing app without changing non-memory modules.

Expected files:

- `tests/test_memory_integration_with_agent_contract.py`
- documentation updates if approved

Expected verification:

- instantiate `Agent(context, Memory())`
- process a simple turn with mocked model/tool dependencies
- verify `history` persists
- verify semantic outbox or semantic memory is created according to policy
- verify existing travel keys still work

Manual verification:

```bash
python3 loop.py
```

Then manually run a short travel interaction:

```text
我想去成都
玩3天
预算3000元
```

Expected behavior:

- the app still responds normally
- memory database is created
- history can be inspected after restart

Phase report must answer:

- Did existing behavior change?
- Which commands prove compatibility?
- Which memory artifacts were created?

## 18. Reporting Template For Every Phase

Every completed phase report must include:

```markdown
## 第 N 阶段报告

### 本阶段改动

### 新增文件

### 修改文件

### 公开接口

### 自动验证

命令：
结果：

### 人工验证

步骤：
预期：

### 已知限制

### 请求确认

请审阅本阶段结果，并确认是否进入第 N+1 阶段。
```

## 19. Acceptance Criteria

The full memory-layer implementation is complete only when:

- `from memory import Memory` uses the real implementation.
- Existing `store/retrieve` callers work unchanged.
- `history`, `current_requirement`, `current_itinerary`, and `reset_flag` remain compatible.
- Compatibility KV state persists across process restarts.
- Semantic memories are stored in SQLite and indexed in Qdrant.
- BGE-M3 dense embeddings are used for semantic search.
- Search is scoped by tenant/user/project and excludes deleted or expired memories.
- Users can view, edit, export, import, and delete memory.
- Each memory result can include source evidence.
- Sensitive values are redacted before durable semantic storage.
- Each implementation phase has a report and explicit user approval before moving on.

## 20. Open Implementation Decisions

These are left for the implementation plan, not code improvisation:

- exact Pydantic class field names for search results
- whether SQLite non-JSON compatibility values use pickle or a safer custom serializer for current dataclasses
- exact Qdrant Python client test strategy: mock client, local mode, or running localhost Qdrant smoke tests
- exact dependency additions in `pyproject.toml`
- exact debug helper names for human inspection
