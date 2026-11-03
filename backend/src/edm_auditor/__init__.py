"""EDM-Auditor backend package."""
from .model_config import (
    LegalActChunkingConfig,
    LegalActProcessingConfig,
    detect_source_language,
    ModelConfig,
    ModelPreset,
    ModelSettings,
)
from .model_providers import (
    LLMProvider,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLMProvider,
    StubLLMProvider,
    create_embedding_provider,
    create_llm_provider,
)

__all__ = [
    "LLMProvider",
    "ModelConfig",
    "ModelPreset",
    "ModelSettings",
    "LegalActProcessingConfig",
    "LegalActChunkingConfig",
    "detect_source_language",
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleLLMProvider",
    "StubLLMProvider",
    "create_embedding_provider",
    "create_llm_provider",
]
