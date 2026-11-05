"""Embedding provider contracts."""

from collections.abc import Sequence
from typing import Protocol

from .exceptions import EmbeddingError

Vector = tuple[float, ...]


class EmbeddingProvider(Protocol):
    """Provider used to embed documents and search queries."""

    model_name: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        """Return one vector for each input text."""

    def embed_query(self, text: str) -> Vector:
        """Return a vector for one query."""


def validate_vectors(vectors: Sequence[Vector], expected_count: int, dimension: int) -> None:
    """Validate a provider response before it reaches the vector store."""
    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"provider returned {len(vectors)} vectors for {expected_count} texts"
        )
    if any(len(vector) != dimension for vector in vectors):
        raise EmbeddingError(f"all vectors must have dimension {dimension}")
