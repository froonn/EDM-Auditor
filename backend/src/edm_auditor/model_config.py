"""Typed configuration for embedding and language model providers."""

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from typing import Any


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

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model must not be empty")
        if self.dimension is not None and self.dimension <= 0:
            raise ValueError("dimension must be positive")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

    def api_key(self) -> str | None:
        """Read the secret named by the config without storing the secret itself."""
        return os.getenv(self.api_key_env) if self.api_key_env else None


@dataclass(frozen=True, slots=True)
class ModelPreset:
    """Pair of profile names used by an application environment."""

    embedding: str
    llm: str


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Resolved embedding and LLM settings."""

    embedding: ModelConfig
    llm: ModelConfig
    preset_name: str = "offline"

    @classmethod
    def from_toml(
        cls,
        path: str | Path = Path("config/models.toml"),
        *,
        preset_name: str | None = None,
    ) -> "ModelSettings":
        config_path = Path(path)
        with config_path.open("rb") as file:
            data = tomllib.load(file)

        profiles = data.get("profiles", {})
        embedding_profiles = profiles.get("embedding", {})
        llm_profiles = profiles.get("llm", {})
        presets = data.get("presets", {})
        selected_name = preset_name or os.getenv("EDM_MODEL_PRESET", "offline")
        try:
            selected = presets[selected_name]
            embedding = _model_config(embedding_profiles[selected["embedding"]])
            llm = _model_config(llm_profiles[selected["llm"]])
        except KeyError as error:
            raise ValueError(f"unknown model preset or profile: {error.args[0]}") from error
        return cls(embedding=embedding, llm=llm, preset_name=selected_name)

    @classmethod
    def from_env(cls) -> "ModelSettings":
        """Load the configured file, allowing only non-secret path/preset overrides."""
        path = Path(os.getenv("EDM_MODEL_CONFIG", "config/models.toml"))
        return cls.from_toml(path, preset_name=os.getenv("EDM_MODEL_PRESET"))


def _model_config(values: dict[str, Any]) -> ModelConfig:
    return ModelConfig(
        provider=str(values["provider"]),
        model=str(values["model"]),
        base_url=values.get("base_url"),
        api_key_env=values.get("api_key_env"),
        dimension=values.get("dimension"),
        temperature=float(values.get("temperature", 0.1)),
        max_tokens=int(values.get("max_tokens", 2000)),
    )
