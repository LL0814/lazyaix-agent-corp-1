---
name: building-enterprise-memory
description: Use when designing, implementing, reviewing, or testing enterprise agent memory systems, long-term memory layers, implicit memory extraction, vector recall, outbox workers, or staged TDD delivery with Chinese reports and human verification.
---

# Building Enterprise Memory

## Overview

Build agent memory as an inspectable engineering system: staged plan, explicit interfaces, TDD, durable storage, worker processing, integration tests, and Chinese checkpoint reports. Favor Claude/Codex-like memory behavior: implicit extraction, scoped recall, durable records, auditability, and user-controllable verification.

## Operating Contract

- Write plans, checkpoint reports, and user-facing explanations in Chinese unless the user asks otherwise.
- Do not deliver a one-shot black box. Split work into reviewable stages and report after each stage.
- Before editing a stage, state what will be changed. After the stage, state files changed, interfaces added, tests run, and how the user can manually verify.
- Use TDD for behavior changes: write failing tests first, verify failure, implement minimally, then verify green.
- Keep deterministic tests independent of paid or network AI calls. Use fake embedding/extractor providers in unit tests and guarded real-provider checks for manual/integration testing.
- Never store secrets in files or logs. Treat API keys, HF tokens, and DB credentials as sensitive.

## Workflow

1. **Scan first**: inspect branch status, existing context/history modules, model providers, config loading, storage dependencies, and test style.
2. **Write the memory plan**: define memory kinds, storage mapping, interfaces, data flow, failure handling, privacy/redaction, observability, and staged acceptance criteria.
3. **Stage interfaces and config**: create types and provider contracts before storage logic. Include tests for validation, defaults, and dynamic input.
4. **Stage durable storage**: add SQLite tables for records, KV state, outbox, audit, summaries, tombstones, and metadata. Add idempotent migrations.
5. **Stage embeddings and vector index**: add an embedding provider contract, local Ollama `bge-m3` support when available, fake provider for tests, and Qdrant-backed semantic search.
6. **Stage extraction**: add an AI extractor interface for implicit memory extraction from natural dialogue. Extract multiple memory items per turn when evidence supports it. Each item must include kind, scope, content, metadata, confidence, source text, and timestamp.
7. **Stage outbox worker**: raw conversation creates pending events; worker consumes events, calls extractor, redacts/dedupes, writes durable memory, and marks events done or failed with `last_error`.
8. **Stage agent integration**: keep conversation history separate from long-term memory. Before model response, retrieve relevant memories and assemble a concise memory context block.
9. **Stage tests and manual QA**: add unit tests for every interface, integration tests for the full data flow, and manual prompts for each memory kind.

## Memory Taxonomy

Use fixed enum values only as categories, not as hardcoded content.

| Kind | Typical Storage | Purpose |
| --- | --- | --- |
| `kv_state` | SQLite KV | Stable state, toggles, counters, user/project preferences that need exact lookup. |
| `episodic` | Qdrant vector + SQLite metadata | Events, incidents, examples, dated experiences, "what happened when". |
| `semantic` | Qdrant vector + SQLite metadata | Facts, preferences, domain knowledge, reusable user profile items. |
| `procedural` | SQLite metadata + optional vector | User's preferred workflows, checklists, ordering rules, "how to do things". |
| `summary` | SQLite text records | Conversation/project summaries used to compact context or bootstrap future turns. |
| `tombstone` | SQLite audit/tombstone table | Deletions, superseded memories, redaction markers, and compliance trace. |

If a user asks whether memory types are "written dead", explain: the allowed category strings are strict for reliability; the content, metadata, scope, and extraction source are dynamic.

## Core Interfaces

Adapt names to the repo, but keep these boundaries:

- `MemoryRecord`: tenant/user/project/thread scope, kind, content, metadata, status, confidence, timestamps, source hash.
- `MemoryStore`: `remember`, `search`, `forget`, `retrieve`, `store`, `process_outbox`, `debug_counts`.
- `EmbeddingProvider`: `embed(text: str) -> list[float]`; fake provider for tests, Ollama `bge-m3` for local use.
- `MemoryExtractor`: converts natural dialogue into zero or more candidate memory items; DeepSeek/Kimi/OpenAI-compatible providers are optional implementations.
- `OutboxStore`: creates pending events, leases events to workers, records retries, marks done/failed.
- `MemoryWorker`: owns extraction, redaction, dedupe, durable write, vector indexing, and failure bookkeeping.

## Data Flow

Use this chain for explanations, tests, and reports:

```text
natural dialogue
-> loop.py / Agent receives user turn
-> conversation history is stored as short-term context
-> Memory.remember or Agent._remember enqueues an outbox event
-> outbox row is pending in SQLite
-> worker leases pending event
-> extractor classifies and extracts memory candidates
-> redaction/dedupe/validation runs
-> memory is written to SQLite and/or Qdrant by kind
-> outbox row becomes done, or failed with attempts and last_error
-> later query retrieves relevant memories
-> prompt receives a concise memory context block
```

Do not skip the outbox for implicit extraction. It gives auditability, retry, and separation between "captured raw signal" and "accepted long-term memory".

## Checkpoint Report Template

After each stage, report in Chinese:

```markdown
## 阶段完成报告

- 本阶段目标：
- 改动文件：
- 新增/修改接口：
- 数据流变化：
- 自动测试：
- 人工验证方法：
- 风险和下一步：
```

When the user asks "这次改动了哪些地方", answer with exact file paths and the purpose of each change. When the user asks "这个接口在哪里实现", list interface path, concrete implementation path, and tests.

## Testing Requirements

- Every public memory API must have at least one unit test.
- Integration tests must show state transitions, especially `outbox: pending -> processing/leased -> done/failed`.
- Tests should print or assert data-flow facts: original dialogue, generated event, extracted candidate, stored record, vector lookup result, and recalled prompt block.
- Use fake providers for deterministic assertions. Add separate manual commands for real Qdrant/Ollama/DeepSeek/Kimi verification.
- Run the full relevant test suite before claiming completion.

## Manual Verification Prompts

When the user wants prompts to test memory, read `references/prompt-patterns.md` and provide fresh implicit prompts. Avoid using the same examples repeatedly; otherwise the user cannot tell which turn created the memory.

## Common Mistakes

- Do not write demo memory content into defaults or constructors.
- Do not call the LLM in deterministic tests.
- Do not merge short-term history and durable memory into one undifferentiated blob.
- Do not lose failed extraction events silently; record `attempts` and `last_error`.
- Do not over-recall. Only inject memories relevant to the current user query.
- Do not force push or delete remote branches while packaging the work unless the user explicitly asks.
