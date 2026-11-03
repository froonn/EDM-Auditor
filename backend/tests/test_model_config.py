from pathlib import Path

import pytest

from edm_auditor.model_config import (
    LegalActProcessingConfig,
    ModelConfig,
    ModelSettings,
)
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


def test_lm_studio_declares_json_schema_output() -> None:
    settings = ModelSettings.from_toml(CONFIG_PATH, preset_name="lm-studio")

    assert settings.llm.structured_output == "json_schema"


def test_google_ai_studio_preset_uses_official_provider() -> None:
    settings = ModelSettings.from_toml(CONFIG_PATH, preset_name="google-ai-studio")

    assert settings.embedding.provider == "google-ai-studio"
    assert settings.embedding.model == "gemini-embedding-2"
    assert settings.llm.provider == "google-ai-studio"
    assert settings.extractor is not None
    assert settings.extractor.api_key_env == "GEMINI_API_KEY"


def test_processing_config_is_loaded_from_model_config() -> None:
    settings = ModelSettings.from_toml(CONFIG_PATH, preset_name="offline")

    assert settings.processing.max_chunk_chars == 4000
    assert settings.processing.max_prompt_chars == 12000
    assert settings.processing.max_response_tokens == 2000
    assert settings.processing.max_rules_per_chunk == 20
    assert settings.processing.source_language == "auto"
    assert settings.processing.processing_version == "1"


def test_processing_config_rejects_invalid_language() -> None:
    with pytest.raises(ValueError, match="source_language"):
        LegalActProcessingConfig(source_language="de")


def test_invalid_model_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        ModelConfig(provider="deterministic", model="test", dimension=0)


def test_llm_profiles_must_declare_structured_output(tmp_path: Path) -> None:
    config = tmp_path / "models.toml"
    config.write_text(
        """
[profiles.embedding.offline]
provider = "deterministic"
model = "deterministic-v1"
dimension = 32

[profiles.llm.incomplete]
provider = "stub"
model = "stub-v1"

[presets.test]
embedding = "offline"
llm = "incomplete"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="structured_output"):
        ModelSettings.from_toml(config, preset_name="test")
