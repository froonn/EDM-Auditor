from pathlib import Path

import pytest

from edm_auditor.model_config import (
    LegalActProcessingConfig,
    ModelConfig,
    ModelSettings,
    detect_source_language,
)
from edm_auditor.model_providers import (
    create_embedding_provider,
    create_entity_extraction_provider,
    create_llm_provider,
    create_rule_extraction_provider,
)


CONFIG_PATH = Path(__file__).parents[1] / "config" / "models.toml"


def test_preset_is_required() -> None:
    with pytest.raises(ValueError, match="EDM_MODEL_PRESET"):
        ModelSettings.from_toml(CONFIG_PATH)


def test_offline_preset_no_longer_exists() -> None:
    with pytest.raises(ValueError, match="unknown model preset"):
        ModelSettings.from_toml(CONFIG_PATH, preset_name="offline")


@pytest.mark.parametrize(
    "factory",
    [
        create_llm_provider,
        create_entity_extraction_provider,
        create_rule_extraction_provider,
    ],
)
def test_stub_provider_is_rejected(factory) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        factory(ModelConfig(provider="stub", model="stub-v1"))


def test_deterministic_embedding_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported embedding provider"):
        create_embedding_provider(
            ModelConfig(provider="deterministic", model="deterministic-v1", dimension=32)
        )


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
    settings = ModelSettings.from_toml(CONFIG_PATH, preset_name="google-ai-studio")

    assert settings.processing.chunking.max_chars == 4000
    assert settings.processing.chunking.overlap_chars == 0
    assert settings.processing.max_prompt_chars == 12000
    assert settings.processing.max_response_tokens == 2000
    assert settings.processing.chunking.max_rules_per_chunk == 20
    assert settings.processing.source_language == "auto"
    assert settings.processing.processing_version == "1"
    assert settings.extractor is not None
    assert settings.extractor.request_timeout_seconds == 30
    assert settings.extractor.retry_attempts == 3


def test_processing_config_rejects_invalid_language() -> None:
    with pytest.raises(ValueError, match="source_language"):
        LegalActProcessingConfig(source_language="de")


def test_source_language_can_be_overridden_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EDM_SOURCE_LANGUAGE", "ru")
    monkeypatch.setenv("EDM_MODEL_PRESET", "lm-studio")

    settings = ModelSettings.from_env()

    assert settings.processing.source_language == "ru"


def test_source_language_detection_uses_script_ratio() -> None:
    assert detect_source_language("Требование должно быть выполнено.") == "ru"
    assert detect_source_language("The requirement must be fulfilled.") == "en"


def test_invalid_model_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        ModelConfig(provider="deterministic", model="test", dimension=0)


def test_llm_profiles_must_declare_structured_output(tmp_path: Path) -> None:
    config = tmp_path / "models.toml"
    config.write_text(
        """
[profiles.embedding.local]
provider = "openai-compatible"
model = "embedding"
dimension = 32

[profiles.llm.incomplete]
provider = "openai-compatible"
model = "chat"

[presets.test]
embedding = "local"
llm = "incomplete"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="structured_output"):
        ModelSettings.from_toml(config, preset_name="test")
