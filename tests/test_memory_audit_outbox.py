from pathlib import Path


def test_store_writes_audit_event(tmp_path: Path):
    from memory import Memory

    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    memory.store("reset_flag", True)

    counts = memory.debug_counts()
    assert counts.audit == 1


def test_history_append_creates_outbox_event(tmp_path: Path):
    from memory import Memory

    memory = Memory(config={"MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3")})

    memory.store("history", [{"input": "喜欢安静酒店", "response": "已记录"}])

    counts = memory.debug_counts()
    assert counts.outbox == 1


def test_history_outbox_is_deduplicated(tmp_path: Path):
    from memory import Memory

    db_path = tmp_path / "memory.sqlite3"
    memory = Memory(config={"MEMORY_DB_PATH": str(db_path)})
    history = [{"input": "喜欢安静酒店", "response": "已记录"}]

    memory.store("history", history)
    memory.store("history", history)

    assert memory.debug_counts().outbox == 1


def test_list_outbox_returns_payload(tmp_path: Path):
    from memory.backends.sqlite_store import SQLiteMemoryStore

    db_path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(str(db_path))

    event_id = store.enqueue_outbox(
        "memory.semantic_candidate.created",
        {"text": "用户喜欢安静酒店"},
        dedupe_key="turn:1",
    )

    rows = store.list_outbox()
    assert event_id is not None
    assert rows[0]["event_type"] == "memory.semantic_candidate.created"
    assert rows[0]["payload"]["text"] == "用户喜欢安静酒店"


def test_generate_memories_false_skips_history_outbox(tmp_path: Path):
    from memory import Memory

    memory = Memory(
        config={
            "MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3"),
            "MEMORY_GENERATE_MEMORIES": False,
        }
    )

    memory.store("history", [{"input": "喜欢安静酒店", "response": "已记录"}])

    counts = memory.debug_counts()
    assert counts.audit == 1
    assert counts.outbox == 0
