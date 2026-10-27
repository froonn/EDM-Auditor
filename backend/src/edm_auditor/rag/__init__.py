"""Chunking, indexing, and semantic search for legal text."""

from .chunking import chunk_text
from .embeddings import DeterministicEmbeddingProvider, EmbeddingProvider
from .indexer import IndexSource, RAGIndexer
from .models import SearchResult, TextChunk
from .search import RAGSearch
from .vector_store import SQLiteVectorStore

__all__ = [
    "DeterministicEmbeddingProvider",
    "EmbeddingProvider",
    "IndexSource",
    "RAGIndexer",
    "RAGSearch",
    "SQLiteVectorStore",
    "SearchResult",
    "TextChunk",
    "chunk_text",
]
