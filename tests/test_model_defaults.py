from pathlib import Path

from models.model import Model


def test_default_model_is_deepseek_v4_pro():
    assert Model.DEFAULT_MODEL == "deepseek:deepseek-v4-pro"


def test_env_example_defaults_to_deepseek_without_real_keys():
    content = Path(".env.example").read_text(encoding="utf-8")

    assert "MODEL=deepseek:deepseek-v4-pro" in content
    assert "sk-" not in content
    assert "kimi:kimi-for-coding" not in [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
