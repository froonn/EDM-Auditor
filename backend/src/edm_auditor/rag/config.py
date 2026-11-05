"""Environment-backed RAG configuration."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RAGSettings:
    """Local RAG index location; the embedding model comes from the model preset."""

    index_path: Path = Path("data/rag-index.sqlite3")

    @classmethod
    def from_env(cls) -> "RAGSettings":
        return cls(
            index_path=Path(os.getenv("RAG_INDEX_PATH", "data/rag-index.sqlite3")),
        )
