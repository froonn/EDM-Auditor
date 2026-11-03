"""EDM-Auditor backend package."""
from .model_config import (
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
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleLLMProvider",
    "StubLLMProvider",
    "create_embedding_provider",
    "create_llm_provider",
]
