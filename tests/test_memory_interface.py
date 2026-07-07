def test_memory_imports_real_class():
    from memory import Memory

    memory = Memory()

    assert hasattr(memory, "store")
    assert hasattr(memory, "retrieve")


def test_store_retrieve_in_memory_before_sqlite_backend():
    from memory import Memory

    memory = Memory(config={"MEMORY_BACKEND": "memory"})

    memory.store("hello", {"world": 1})

    assert memory.retrieve("hello") == {"world": 1}


def test_default_config_values():
    from memory.config import MemoryConfig

    config = MemoryConfig.from_env({})

    assert config.enable_memory is True
    assert config.use_memories is True
    assert config.generate_memories is True
    assert config.tenant_id == "local"
    assert config.user_id == "default"
    assert config.project_id == "lazyaiX-agent-corp-1"
    assert config.db_path == ".memory/memory.sqlite3"
    assert config.qdrant_url == "http://localhost:6333"
    assert config.qdrant_collection == "agent_memories_v1"
    assert config.embedding_model == "BAAI/bge-m3"
    assert config.embedding_dimension == 1024


def test_memory_enums_are_stable():
    from memory.models import MemoryKind, MemoryScope, MemoryStatus

    assert MemoryScope.PROJECT == "project"
    assert MemoryKind.SEMANTIC == "semantic"
    assert MemoryStatus.ACTIVE == "active"
