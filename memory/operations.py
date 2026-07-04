"""Memory operation parsing and application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .storage import JsonMemoryStore
except ImportError:
    from storage import JsonMemoryStore


@dataclass(frozen=True)
class MemoryOperation:
    action: str
    key: str
    value: Any = None
    old_value: Any = None
    new_value: Any = None


SUPPORTED_ACTIONS = {
    "create",
    "append",
    "update",
    "delete",
    "remove_item",
    "replace_item",
}


def parse_operations(payload: Any) -> list[MemoryOperation]:
    """Convert an LLM JSON payload into safe memory operations."""
    raw_operations = []
    if isinstance(payload, dict):
        raw_operations = payload.get("operations") or []
    elif isinstance(payload, list):
        raw_operations = payload

    operations = []
    for raw in raw_operations:
        if not isinstance(raw, dict):
            continue

        action = str(raw.get("action", "")).strip()
        key = str(raw.get("key", "")).strip()
        if action not in SUPPORTED_ACTIONS or not key:
            continue

        operations.append(
            MemoryOperation(
                action=action,
                key=key,
                value=raw.get("value"),
                old_value=raw.get("old_value"),
                new_value=raw.get("new_value"),
            )
        )
    return operations


def apply_operation(store: JsonMemoryStore, operation: MemoryOperation) -> bool:
    """Apply one normalized operation to the JSON store."""
    if operation.action == "create":
        return store.create(operation.key, operation.value)
    if operation.action == "append":
        return store.append(operation.key, operation.value)
    if operation.action == "update":
        return store.update(operation.key, operation.value)
    if operation.action == "delete":
        return store.delete(operation.key)
    if operation.action == "remove_item":
        return store.remove_item(operation.key, operation.value)
    if operation.action == "replace_item":
        return store.replace_item(
            operation.key,
            operation.old_value,
            operation.new_value,
        )
    return False
