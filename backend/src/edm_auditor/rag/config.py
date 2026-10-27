"""Environment-backed RAG configuration."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RAGSettings:
    """Local RAG settings with an offline-safe default provider."""

    index_path: Path = Path("data/rag-index.sqlite3")
    embedding_model: str = "deterministic-v1"
    embedding_dimension: int = 32

    @classmethod
    def from_env(cls) -> "RAGSettings":
        dimension = int(os.getenv("RAG_EMBEDDING_DIMENSION", "32"))
        if dimension <= 0:
            raise ValueError("RAG_EMBEDDING_DIMENSION must be positive")
        return cls(
            index_path=Path(os.getenv("RAG_INDEX_PATH", "data/rag-index.sqlite3")),
            embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "deterministic-v1"),
            embedding_dimension=dimension,
        )
