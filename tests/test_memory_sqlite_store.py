from pathlib import Path


def test_sqlite_store_round_trips_json_value(tmp_path: Path):
    from memory.backends.sqlite_store import SQLiteMemoryStore

    db_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(str(db_path))

    store.set_kv("history", [{"input": "我想去成都", "response": "好的"}])

    assert store.get_kv("history") == [{"input": "我想去成都", "response": "好的"}]


def test_memory_persists_across_instances(tmp_path: Path):
    from memory import Memory

    db_path = tmp_path / "memory.sqlite3"
    config = {"MEMORY_BACKEND": "sqlite", "MEMORY_DB_PATH": str(db_path)}

    first = Memory(config=config)
    first.store("current_requirement", {"destination": "成都", "days": 3})

    second = Memory(config=config)

    assert second.retrieve("current_requirement") == {"destination": "成都", "days": 3}


def test_non_json_local_object_round_trip(tmp_path: Path):
    from memory.backends.sqlite_store import SQLiteMemoryStore

    db_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(str(db_path))
    value = {"items": {1, 2, 3}}

    store.set_kv("non_json", value)

    assert store.get_kv("non_json") == value


def test_debug_counts_reports_kv_rows(tmp_path: Path):
    from memory import Memory

    db_path = tmp_path / "memory.sqlite3"
    memory = Memory(config={"MEMORY_BACKEND": "sqlite", "MEMORY_DB_PATH": str(db_path)})

    memory.store("reset_flag", True)

    assert memory.debug_counts().kv == 1


def test_env_style_overrides_are_applied(tmp_path: Path):
    from memory.config import MemoryConfig

    db_path = tmp_path / "memory.sqlite3"

    config = MemoryConfig.from_env(
        {"MEMORY_BACKEND": "sqlite", "MEMORY_DB_PATH": str(db_path)}
    )

    assert config.backend == "sqlite"
    assert config.db_path == str(db_path)
