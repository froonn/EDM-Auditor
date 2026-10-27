"""Domain models used by the RAG indexer."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A source-preserving fragment of legal text."""

    chunk_id: str
    legal_act_id: int
    rule_id: int | None
    text: str
    chunk_index: int
    start_char: int
    end_char: int
    chunking_version: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A chunk returned by semantic search."""

    chunk: TextChunk
    score: float


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    """Metadata describing the vectors stored in an index."""

    embedding_model: str
    dimension: int
    chunking_version: str
