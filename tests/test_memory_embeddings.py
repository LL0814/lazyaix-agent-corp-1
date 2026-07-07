import pytest

from memory.embeddings import BGEM3EmbeddingProvider, FakeEmbeddingProvider


def test_fake_embedding_provider_is_deterministic():
    provider = FakeEmbeddingProvider(dimension=1024)

    first = provider.embed("我喜欢安静的酒店")
    second = provider.embed("我喜欢安静的酒店")

    assert len(first) == 1024
    assert first == second


def test_fake_embedding_provider_changes_with_text():
    provider = FakeEmbeddingProvider(dimension=1024)

    first = provider.embed("安静酒店")
    second = provider.embed("热闹餐厅")

    assert first != second


def test_bge_provider_loads_lazily():
    provider = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3", use_fp16=True)

    assert provider._model is None


def test_bge_provider_missing_dependency_error_is_clear(monkeypatch):
    provider = BGEM3EmbeddingProvider(model_name="BAAI/bge-m3")

    def fail_import():
        raise ImportError("No module named FlagEmbedding")

    monkeypatch.setattr(provider, "_import_model_class", fail_import)

    with pytest.raises(RuntimeError, match="FlagEmbedding"):
        provider.embed("测试")
