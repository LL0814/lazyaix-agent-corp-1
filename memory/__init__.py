"""Memory module: JSON-backed key-value storage with CRUD operations.

数据以 JSON 格式持久化到项目根目录下的 ``memory/memory.json`` 文件中。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class Memory:
    """基于本地 JSON 文件的记忆存储，支持增删改查（CRUD）。"""

    def __init__(self, path: str | Path | None = None) -> None:
        """初始化存储。

        Args:
            path: JSON 文件路径，默认为 ``memory/memory.json``。
        """
        if path is None:
            path = Path(__file__).resolve().parent / "memory.json"
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        """确保存储文件存在。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}", encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        """从 JSON 文件加载全部数据。"""
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        """将数据保存到 JSON 文件。"""
        tmp_path = self._path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(self._path)

    # ---------- CRUD ----------

    def create(self, key: str, value: Any) -> bool:
        """新增一条记忆。若 key 已存在则返回 False，不覆盖。

        Args:
            key: 记忆键名。
            value: 要保存的值，需可 JSON 序列化。

        Returns:
            是否创建成功。
        """
        with self._lock:
            data = self._load()
            if key in data:
                return False
            data[key] = value
            self._save(data)
            return True

    def retrieve(self, key: str) -> Any | None:
        """读取一条记忆。"""
        with self._lock:
            data = self._load()
            return data.get(key)

    def update(self, key: str, value: Any) -> bool:
        """更新一条记忆。若 key 不存在则返回 False。

        Args:
            key: 记忆键名。
            value: 新值，需可 JSON 序列化。

        Returns:
            是否更新成功。
        """
        with self._lock:
            data = self._load()
            if key not in data:
                return False
            data[key] = value
            self._save(data)
            return True

    def delete(self, key: str) -> bool:
        """删除一条记忆。若 key 不存在则返回 False。"""
        with self._lock:
            data = self._load()
            if key not in data:
                return False
            del data[key]
            self._save(data)
            return True

    def exists(self, key: str) -> bool:
        """判断某条记忆是否存在。"""
        with self._lock:
            data = self._load()
            return key in data

    def list(self) -> list[str]:
        """返回所有记忆的键名列表。"""
        with self._lock:
            data = self._load()
            return list(data.keys())

    def all(self) -> dict[str, Any]:
        """返回所有记忆的副本。"""
        with self._lock:
            return dict(self._load())

    # 兼容 agent.py / loop.py 中约定的接口

    def store(self, key: str, value: Any) -> None:
        """保存或覆盖一条记忆（兼容旧接口）。"""
        with self._lock:
            data = self._load()
            data[key] = value
            self._save(data)
