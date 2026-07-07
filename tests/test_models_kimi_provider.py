from models.factory import ProviderFactory
from models.providers.kimi import KimiProvider


def test_provider_factory_creates_kimi_code_provider_on_moonshot_endpoint():
    provider = ProviderFactory.create(
        provider="kimi",
        api_key="kimi-key",
        model_name="kimi-k2.7-code-highspeed",
    )

    assert isinstance(provider, KimiProvider)
    assert provider.model_name == "kimi-k2.7-code-highspeed"
    assert provider.base_url == "https://api.moonshot.cn/v1"


def test_kimi_provider_supports_available_code_models():
    assert "kimi-k2.7-code-highspeed" in KimiProvider.supported_models
    assert "kimi-k2.7-code" in KimiProvider.supported_models
