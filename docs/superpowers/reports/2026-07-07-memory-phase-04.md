# 第 4 阶段报告：脱敏和记忆候选分类

## 本阶段目标

在第 3 阶段 outbox 事件之后，先补齐“进入长期记忆前的安全闸门”：提供敏感信息脱敏能力，以及一个可替换的规则型记忆候选分类器。后续阶段可以把 outbox 里的候选文本交给这两个接口处理，再进入 embedding 和 Qdrant 写入。

## 本阶段改动

- 新增 `memory/redaction.py`，提供 `redact_text()`，用于替换常见 secret、Bearer token、private key 和 cookie/session 类信息。
- 新增 `memory/classifier.py`，提供 `classify_memory_candidate()`，用于把候选文本初步分为 `semantic`、`procedural` 或跳过。
- 扩展 `memory/models.py`，新增 `RedactionResult` 和 `MemoryClassification` 两个结构化结果模型。
- 新增 `tests/test_memory_redaction_classifier.py`，覆盖脱敏和规则分类。

## 新增文件

- `memory/redaction.py`
- `memory/classifier.py`
- `tests/test_memory_redaction_classifier.py`
- `docs/superpowers/reports/2026-07-07-memory-phase-04.md`

## 修改文件

- `memory/models.py`

## 公开接口

- `RedactionResult`
  - 位置：`memory/models.py`
  - 字段：`text`、`redacted`、`markers`
- `MemoryClassification`
  - 位置：`memory/models.py`
  - 字段：`should_remember`、`kind`、`confidence`、`importance`、`reason`
- `redact_text(text: str) -> RedactionResult`
  - 位置：`memory/redaction.py`
  - 用途：把文本里的敏感片段替换为 `[REDACTED:<type>]`
- `classify_memory_candidate(text: str) -> MemoryClassification`
  - 位置：`memory/classifier.py`
  - 用途：规则判断一段候选文本是否值得进入长期记忆，以及建议记忆类型

## 当前分类规则

- 命中流程、工作方式、固定要求类关键词时，分类为 `MemoryKind.PROCEDURAL`。
- 命中偏好、习惯、项目事实类关键词时，分类为 `MemoryKind.SEMANTIC`。
- 内容过短或未命中稳定记忆规则时，`should_remember=False`，默认不进入长期记忆。

## 自动验证

RED 命令：

```bash
uv run pytest tests/test_memory_redaction_classifier.py -v
```

RED 结果：

```text
7 failed in 0.04s
```

失败原因：

- `memory.redaction` 尚不存在。
- `memory.classifier` 尚不存在。

GREEN 命令：

```bash
uv run pytest tests/test_memory_redaction_classifier.py -v
```

GREEN 结果：

```text
7 passed in 0.05s
```

回归测试命令：

```bash
uv run pytest tests/test_memory_interface.py tests/test_memory_sqlite_store.py tests/test_memory_audit_outbox.py tests/test_memory_redaction_classifier.py -v
```

回归测试结果：

```text
21 passed in 0.06s
```

全量测试命令：

```bash
uv run pytest -q
```

全量测试结果：

```text
76 passed in 0.28s
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

脱敏验证命令：

```bash
uv run python -c "from memory.redaction import redact_text; print(redact_text('token=sk-abcdefghijklmnopqrstuvwxyz123456').text)"
```

预期：

```text
token=[REDACTED:secret]
```

实际：

```text
token=[REDACTED:secret]
```

分类验证命令：

```bash
uv run python -c "from memory.classifier import classify_memory_candidate; print(classify_memory_candidate('以后每完成一步都写中文阶段报告并等待确认'))"
```

预期：输出包含 `should_remember=True` 和 `MemoryKind.PROCEDURAL`。

实际：

```text
should_remember=True kind=<MemoryKind.PROCEDURAL: 'procedural'> confidence=0.8 importance=0.8 reason='命中流程或工作方式偏好'
```

## 已知限制

- 当前分类器是规则型实现，不是 LLM 分类器，也没有使用 embedding 模型。
- 当前脱敏规则只覆盖常见 secret 形态，不等于完整 DLP 系统。
- 当前阶段只是提供接口，还没有把脱敏和分类接入 outbox 消费链路。
- 当前阶段还没有写入 Qdrant，也没有生成向量。
- 当前工作区存在外部生成的 `.idea/` 变更，本阶段没有提交这些文件。

## 请求确认

请审阅本阶段结果，并确认是否进入第 5 阶段：BGE-M3 Embedding Provider。
