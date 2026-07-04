"""JSON-backed storage for structured preference memories."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any


class JsonMemoryStore:
    """Persist preference memories as string values in a JSON object."""

    _SEPARATOR = "，"
    _TEXT_SEPARATORS = re.compile(r"[，,、/;；]|\s+和\s+|\s+以及\s+")

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path(__file__).resolve().parent / "memory.json"
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}", encoding="utf-8")

    def _load_unlocked(self) -> dict[str, str]:
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return {}

        if not isinstance(data, dict):
            return {}
        return {
            str(key).strip(): str(value).strip()
            for key, value in data.items()
            if str(key).strip() and str(value).strip()
        }

    def _save_unlocked(self, data: dict[str, str]) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(self._path)

    def normalize_key(self, key: Any) -> str:
        return str(key).strip()

    def normalize_items(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = self._TEXT_SEPARATORS.split(value)
        elif isinstance(value, (list, tuple, set)):
            raw_items = value
        else:
            raw_items = [value]

        items = []
        for raw_item in raw_items:
            item = str(raw_item).strip(" \n\t。，,.！!；;")
            if item and item not in items:
                items.append(item)
        return items

    def normalize_value(self, value: Any) -> str:
        return self._SEPARATOR.join(self.normalize_items(value))

    def _strip_action_prefix(self, item: str) -> tuple[str, str]:
        for prefix in ("吃", "喝", "用", "玩", "看", "听"):
            if item.startswith(prefix) and len(item) > len(prefix):
                return prefix, item[len(prefix):]
        return "", item

    def _matches_removed_category(self, remove_item: str, existing_item: str) -> bool:
        if existing_item == remove_item:
            return True

        remove_prefix, remove_core = self._strip_action_prefix(remove_item)
        existing_prefix, existing_core = self._strip_action_prefix(existing_item)
        if not remove_core or len(remove_core) < 2:
            return False

        if remove_prefix and existing_prefix and remove_prefix != existing_prefix:
            return False
        return remove_core in existing_core

    def create(self, key: str, value: Any) -> bool:
        normalized_key = self.normalize_key(key)
        normalized_value = self.normalize_value(value)
        if not normalized_key or not normalized_value:
            return False
        with self._lock:
            data = self._load_unlocked()
            if normalized_key in data:
                return False
            data[normalized_key] = normalized_value
            self._save_unlocked(data)
            return True

    def retrieve(self, key: str) -> str | None:
        normalized_key = self.normalize_key(key)
        with self._lock:
            return self._load_unlocked().get(normalized_key)

    def update(self, key: str, value: Any) -> bool:
        normalized_key = self.normalize_key(key)
        normalized_value = self.normalize_value(value)
        if not normalized_key or not normalized_value:
            return False
        with self._lock:
            data = self._load_unlocked()
            if normalized_key not in data:
                return False
            data[normalized_key] = normalized_value
            self._save_unlocked(data)
            return True

    def delete(self, key: str) -> bool:
        normalized_key = self.normalize_key(key)
        with self._lock:
            data = self._load_unlocked()
            if normalized_key not in data:
                return False
            del data[normalized_key]
            self._save_unlocked(data)
            return True

    def exists(self, key: str) -> bool:
        normalized_key = self.normalize_key(key)
        with self._lock:
            return normalized_key in self._load_unlocked()

    def list(self) -> list[str]:
        with self._lock:
            return list(self._load_unlocked().keys())

    def all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._load_unlocked())

    def append(self, key: str, value: Any) -> bool:
        normalized_key = self.normalize_key(key)
        items = self.normalize_items(value)
        if not normalized_key or not items:
            return False
        with self._lock:
            data = self._load_unlocked()
            existing_items = self.normalize_items(data.get(normalized_key))
            for item in items:
                if item not in existing_items:
                    existing_items.append(item)
            data[normalized_key] = self._SEPARATOR.join(existing_items)
            self._save_unlocked(data)
            return True

    def remove_item(self, key: str, value: Any) -> bool:
        normalized_key = self.normalize_key(key)
        remove_items = set(self.normalize_items(value))
        if not normalized_key or not remove_items:
            return False
        with self._lock:
            data = self._load_unlocked()
            if normalized_key not in data:
                return False
            kept_items = []
            for item in self.normalize_items(data[normalized_key]):
                should_remove = any(
                    self._matches_removed_category(remove_item, item)
                    for remove_item in remove_items
                )
                if not should_remove:
                    kept_items.append(item)
            if kept_items:
                data[normalized_key] = self._SEPARATOR.join(kept_items)
            else:
                del data[normalized_key]
            self._save_unlocked(data)
            return True

    def replace_item(self, key: str, old_value: Any, new_value: Any) -> bool:
        normalized_key = self.normalize_key(key)
        old_items = set(self.normalize_items(old_value))
        new_items = self.normalize_items(new_value)
        if not normalized_key or not old_items or not new_items:
            return False
        with self._lock:
            data = self._load_unlocked()
            if normalized_key not in data:
                return False

            replaced = False
            next_items = []
            for item in self.normalize_items(data[normalized_key]):
                if item in old_items:
                    if not replaced:
                        next_items.extend(new_items)
                    replaced = True
                    continue
                next_items.append(item)

            if not replaced:
                return False
            data[normalized_key] = self._SEPARATOR.join(
                self.normalize_items(next_items)
            )
            self._save_unlocked(data)
            return True

    def store(self, key: str, value: Any) -> None:
        normalized_key = self.normalize_key(key)
        normalized_value = self.normalize_value(value)
        if not normalized_key or not normalized_value:
            return
        with self._lock:
            data = self._load_unlocked()
            data[normalized_key] = normalized_value
            self._save_unlocked(data)
