from models.factory import ProviderFactory
from models.model import Model
from models.providers.deepseek import DeepSeekProvider


def test_provider_factory_creates_deepseek_provider():
    provider = ProviderFactory.create(
        provider="deepseek",
        api_key="ds-key",
        model_name="deepseek-v4-pro",
    )

    assert isinstance(provider, DeepSeekProvider)
    assert provider.model_name == "deepseek-v4-pro"
    assert provider.base_url == "https://api.deepseek.com"


def test_model_resolves_deepseek_api_key_from_deepseek_or_ds_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DS_API_KEY", "ds-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.deepseek.local")

    api_key, base_url = Model._resolve_env_config("deepseek")

    assert api_key == "ds-key"
    assert base_url == "https://example.deepseek.local"
