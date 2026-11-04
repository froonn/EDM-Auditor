"""Typed configuration for embedding and language model providers."""

from dataclasses import dataclass
from dataclasses import replace
import os
from pathlib import Path
import tomllib
import re
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Connection and generation settings for one configured model."""

    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    dimension: int | None = None
    temperature: float = 0.1
    max_tokens: int = 2000
    structured_output: bool | str = False
    request_timeout_seconds: float = 30.0
    retry_attempts: int = 3
    retry_backoff_factor: float = 1.0
    inter_chunk_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model must not be empty")
        if self.dimension is not None and self.dimension <= 0:
            raise ValueError("dimension must be positive")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.retry_attempts < 0:
            raise ValueError("retry_attempts must not be negative")
        if self.retry_backoff_factor < 0:
            raise ValueError("retry_backoff_factor must not be negative")
        if self.inter_chunk_delay_seconds < 0:
            raise ValueError("inter_chunk_delay_seconds must not be negative")

    def api_key(self) -> str | None:
        """Read the secret named by the config without storing the secret itself."""
        return os.getenv(self.api_key_env) if self.api_key_env else None


@dataclass(frozen=True, slots=True)
class ModelPreset:
    """Pair of profile names used by an application environment."""

    embedding: str
    llm: str
    extractor: str | None = None


@dataclass(frozen=True, slots=True)
class LegalActChunkingConfig:
    """Source-preserving chunk limits for legal-act extraction."""

    max_chars: int = 4000
    overlap_chars: int = 0
    max_rules_per_chunk: int = 20

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("chunking.max_chars must be positive")
        if self.overlap_chars < 0 or self.overlap_chars >= self.max_chars:
            raise ValueError(
                "chunking.overlap_chars must be in [0, max_chars)"
            )
        if self.max_rules_per_chunk <= 0:
            raise ValueError("chunking.max_rules_per_chunk must be positive")


@dataclass(frozen=True, slots=True)
class LegalActProcessingConfig:
    """Limits and versions for reproducible legal-act rule extraction."""

    chunking: LegalActChunkingConfig = LegalActChunkingConfig()
    max_prompt_chars: int = 12000
    max_response_tokens: int = 2000
    source_language: str = "auto"
    extraction_schema_version: str = "1"
    prompt_version: str = "1"
    processing_version: str = "1"

    def __post_init__(self) -> None:
        for name in ("max_prompt_chars", "max_response_tokens"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.source_language not in {"auto", "ru", "en"}:
            raise ValueError("source_language must be auto, ru, or en")
        for name in (
            "extraction_schema_version",
            "prompt_version",
            "processing_version",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


def detect_source_language(text: str) -> str:
    """Detect the supported source language using a conservative script ratio."""
    letters = re.findall(r"[^\W\d_]", text, flags=re.UNICODE)
    if not letters:
        return "en"
    cyrillic = sum("\u0400" <= char <= "\u04ff" for char in letters)
    return "ru" if cyrillic / len(letters) >= 0.2 else "en"


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Resolved embedding and LLM settings."""

    embedding: ModelConfig
    llm: ModelConfig
    extractor: ModelConfig | None = None
    processing: LegalActProcessingConfig = LegalActProcessingConfig()
    preset_name: str | None = None

    @classmethod
    def from_toml(
        cls,
        path: str | Path = Path("config/models.toml"),
        *,
        preset_name: str | None = None,
        source_language: str | None = None,
    ) -> "ModelSettings":
        config_path = Path(path)
        if not config_path.exists():
            if (Path("backend") / path).exists():
                config_path = Path("backend") / path
            elif (Path(__file__).resolve().parents[2] / path).exists():
                config_path = Path(__file__).resolve().parents[2] / path

        with config_path.open("rb") as file:
            data = tomllib.load(file)

        profiles = data.get("profiles", {})
        embedding_profiles = profiles.get("embedding", {})
        llm_profiles = profiles.get("llm", {})
        presets = data.get("presets", {})
        processing = _processing_config(
            data.get("legal_act_processing", data.get("processing", {}))
        )
        if source_language is not None:
            processing = replace(processing, source_language=source_language)
        selected_name = preset_name or os.getenv("EDM_MODEL_PRESET")
        if not selected_name:
            raise ValueError("EDM_MODEL_PRESET must name a configured model preset")
        try:
            selected = presets[selected_name]
            embedding = _model_config(embedding_profiles[selected["embedding"]])
            llm = _model_config(
                llm_profiles[selected["llm"]], require_structured_output=True
            )
            extractor_name = selected.get("extractor")
            extractor = (
                _model_config(data.get("profiles", {}).get("extractor", {})[extractor_name])
                if extractor_name
                else None
            )
        except KeyError as error:
            raise ValueError(f"unknown model preset or profile: {error.args[0]}") from error
        return cls(
            embedding=embedding,
            llm=llm,
            extractor=extractor,
            processing=processing,
            preset_name=selected_name,
        )

    @classmethod
    def from_env(cls) -> "ModelSettings":
        """Load the configured file, allowing only non-secret path/preset overrides."""
        for candidate in [
            Path.cwd() / ".env",
            Path.cwd() / "backend" / ".env",
            Path(__file__).resolve().parents[2] / ".env",
            Path(__file__).resolve().parents[2] / "backend" / ".env",
        ]:
            if candidate.exists():
                load_dotenv(candidate)
        path = Path(os.getenv("EDM_MODEL_CONFIG", "config/models.toml"))
        return cls.from_toml(
            path,
            preset_name=os.getenv("EDM_MODEL_PRESET"),
            source_language=os.getenv("EDM_SOURCE_LANGUAGE"),
        )


def _model_config(
    values: dict[str, Any], *, require_structured_output: bool = False
) -> ModelConfig:
    if require_structured_output and "structured_output" not in values:
        raise ValueError("LLM profile must explicitly declare structured_output")
    structured_output = values.get("structured_output", False)
    if structured_output not in (False, "json_object", "json_schema"):
        raise ValueError(
            "structured_output must be false, json_object, or json_schema"
        )
    return ModelConfig(
        provider=str(values["provider"]),
        model=str(values["model"]),
        base_url=values.get("base_url"),
        api_key_env=values.get("api_key_env"),
        dimension=values.get("dimension"),
        temperature=float(values.get("temperature", 0.1)),
        max_tokens=int(values.get("max_tokens", 2000)),
        structured_output=structured_output,
        request_timeout_seconds=float(values.get("request_timeout_seconds", 30)),
        retry_attempts=int(values.get("retry_attempts", 3)),
        retry_backoff_factor=float(values.get("retry_backoff_factor", 1.0)),
        inter_chunk_delay_seconds=float(
            values.get("inter_chunk_delay_seconds", 0)
        ),
    )


def _processing_config(values: dict[str, Any]) -> LegalActProcessingConfig:
    chunking_values = values.get("chunking", values)
    return LegalActProcessingConfig(
        chunking=LegalActChunkingConfig(
            max_chars=int(chunking_values.get("max_chars", 4000)),
            overlap_chars=int(chunking_values.get("overlap_chars", 0)),
            max_rules_per_chunk=int(
                chunking_values.get("max_rules_per_chunk", 20)
            ),
        ),
        max_prompt_chars=int(values.get("max_prompt_chars", 12000)),
        max_response_tokens=int(values.get("max_response_tokens", 2000)),
        source_language=str(values.get("source_language", "auto")),
        extraction_schema_version=str(values.get("extraction_schema_version", "1")),
        prompt_version=str(values.get("prompt_version", "1")),
        processing_version=str(values.get("processing_version", "1")),
    )
