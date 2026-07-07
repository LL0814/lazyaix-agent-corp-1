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
