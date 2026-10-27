"""Build a vector index from legal act text."""

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

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
        self.store.replace(zip(chunks, vectors))
        return len(chunks)
