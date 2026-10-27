"""Errors raised by the RAG layer."""


class RAGError(Exception):
    """Base class for RAG errors."""


class InvalidChunkingConfiguration(RAGError, ValueError):
    """Raised when chunking parameters are invalid."""


class EmbeddingError(RAGError):
    """Raised when an embedding provider cannot create compatible vectors."""


class VectorStoreError(RAGError):
    """Raised when a vector store cannot satisfy an operation."""


class IndexConfigurationError(VectorStoreError, ValueError):
    """Raised when an index is opened with incompatible configuration."""
