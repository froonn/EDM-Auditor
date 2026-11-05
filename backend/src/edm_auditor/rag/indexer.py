"""Build a vector index from legal act text."""

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import tempfile

from .chunking import CHUNKING_VERSION, chunk_text
from .embeddings import EmbeddingProvider, validate_vectors
from .models import TextChunk
from .vector_store import SQLiteVectorStore


@dataclass(frozen=True, slots=True)
class IndexSource:
    """Text and metadata required to create chunks."""

    legal_act_id: int
    text: str
    rule_id: int | None = None
    source_hash: str | None = None


class RAGIndexer:
    """Create a complete, atomically replaced local index."""

    def __init__(
        self,
        store: SQLiteVectorStore,
        provider: EmbeddingProvider,
        *,
        max_chars: int = 1200,
        overlap_chars: int = 120,
        chunking_version: str = CHUNKING_VERSION,
    ) -> None:
        self.store = store
        self.provider = provider
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.chunking_version = chunking_version

    def build(self, sources: Iterable[IndexSource]) -> int:
        chunks, vectors = self._prepare_entries(sources)
        self.store.replace(zip(chunks, vectors))
        return len(chunks)

    def build_atomic(self, sources: Iterable[IndexSource], target_path: str | Path) -> int:
        """Build an index beside the active file and replace it atomically."""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(
            tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            )[1]
        )
        temporary_path.unlink()
        try:
            chunks, vectors = self._prepare_entries(sources)
            temporary_store = SQLiteVectorStore(
                temporary_path,
                embedding_model=self.provider.model_name,
                dimension=self.provider.dimension,
                chunking_version=self.chunking_version,
            )
            temporary_store.replace(zip(chunks, vectors))
            os.replace(temporary_path, target)
            return len(chunks)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _prepare_entries(
        self, sources: Iterable[IndexSource]
    ) -> tuple[list[TextChunk], list[tuple[float, ...]]]:
        chunks: list[TextChunk] = []
        for source in sources:
            chunks.extend(
                chunk_text(
                    source.text,
                    legal_act_id=source.legal_act_id,
                    rule_id=source.rule_id,
                    max_chars=self.max_chars,
                    overlap_chars=self.overlap_chars,
                    chunking_version=self.chunking_version,
                    source_hash=source.source_hash
                    or sha256(source.text.encode("utf-8")).hexdigest(),
                )
            )
        vectors = self.provider.embed_documents([chunk.text for chunk in chunks])
        validate_vectors(vectors, len(chunks), self.provider.dimension)
        return chunks, list(vectors)
