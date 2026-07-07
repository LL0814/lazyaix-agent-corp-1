from memory.config import MemoryConfig
from models import Model


def test_model_reads_dotenv_without_python_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "MODEL=kimi:kimi-k2.7-code-highspeed\n"
        "KIMI_API_KEY=local-kimi-key\n",
        encoding="utf-8",
    )

    model = Model()

    assert model.provider_name == "kimi"
    assert model.model_name == "kimi-k2.7-code-highspeed"
    assert model.api_key == "local-kimi-key"


def test_memory_config_reads_dotenv_without_python_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MEMORY_EXTRACTOR_PROVIDER", raising=False)
    monkeypatch.delenv("MEMORY_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "MEMORY_EXTRACTOR_PROVIDER=deepseek\n"
        "MEMORY_EMBEDDING_PROVIDER=ollama\n"
        "OLLAMA_EMBEDDING_MODEL=custom-bge\n",
        encoding="utf-8",
    )

    config = MemoryConfig.from_env()

    assert config.extractor_provider == "deepseek"
    assert config.embedding_provider == "ollama"
    assert config.embedding_model == "custom-bge"
