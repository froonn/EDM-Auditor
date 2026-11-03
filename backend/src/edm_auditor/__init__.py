"""EDM-Auditor backend package."""
from .model_config import (
    LegalActChunkingConfig,
    LegalActProcessingConfig,
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
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleLLMProvider",
    "StubLLMProvider",
    "create_embedding_provider",
    "create_llm_provider",
]
