"""Embedding provider contracts and deterministic test implementation."""

from collections.abc import Sequence
from hashlib import sha256
from math import sqrt
import re
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


class DeterministicEmbeddingProvider:
    """Small offline provider for tests and local development."""

    def __init__(self, *, dimension: int = 32, model_name: str = "deterministic-v1") -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self.model_name = model_name

    def _embed(self, text: str) -> Vector:
        values = [0.0] * self.dimension
        tokens = re.findall(r"\w+", text.casefold())
        for token in tokens or [text]:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += 1.0
        norm = sqrt(sum(value * value for value in values))
        return tuple(value / norm for value in values) if norm else tuple(values)

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        return tuple(self._embed(text) for text in texts)

    def embed_query(self, text: str) -> Vector:
        return self._embed(text)


def validate_vectors(vectors: Sequence[Vector], expected_count: int, dimension: int) -> None:
    """Validate a provider response before it reaches the vector store."""
    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"provider returned {len(vectors)} vectors for {expected_count} texts"
        )
    if any(len(vector) != dimension for vector in vectors):
        raise EmbeddingError(f"all vectors must have dimension {dimension}")
