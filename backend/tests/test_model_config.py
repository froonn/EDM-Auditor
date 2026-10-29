from pathlib import Path

import pytest

from edm_auditor.model_config import ModelConfig, ModelSettings
from edm_auditor.model_providers import (
    StubLLMProvider,
    create_embedding_provider,
    create_llm_provider,
)


CONFIG_PATH = Path(__file__).parents[1] / "config" / "models.toml"


def test_offline_preset_creates_offline_providers() -> None:
    settings = ModelSettings.from_toml(CONFIG_PATH, preset_name="offline")

    embedding = create_embedding_provider(settings.embedding)
    llm = create_llm_provider(settings.llm)

    assert embedding.model_name == "deterministic-v1"
    assert embedding.dimension == 32
    assert isinstance(llm, StubLLMProvider)


def test_preset_keeps_api_key_out_of_model_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = ModelSettings.from_toml(CONFIG_PATH, preset_name="openrouter")

    assert settings.llm.api_key_env == "OPENROUTER_API_KEY"
    assert settings.llm.api_key() is None


def test_invalid_model_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        ModelConfig(provider="deterministic", model="test", dimension=0)
