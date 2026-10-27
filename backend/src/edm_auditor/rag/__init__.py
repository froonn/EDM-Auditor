"""Chunking, indexing, and semantic search for legal text."""

from .chunking import chunk_text
from .config import RAGSettings
from .embeddings import DeterministicEmbeddingProvider, EmbeddingProvider
from .indexer import IndexSource, RAGIndexer
from .ingestion import DatabaseIndexSourceLoader, TextLegalActIngestor
from .models import SearchResult, TextChunk
from .search import RAGSearch
from .vector_store import SQLiteVectorStore

__all__ = [
    "DeterministicEmbeddingProvider",
    "DatabaseIndexSourceLoader",
    "EmbeddingProvider",
    "IndexSource",
    "RAGIndexer",
    "RAGSettings",
    "RAGSearch",
    "SQLiteVectorStore",
    "SearchResult",
    "TextLegalActIngestor",
    "TextChunk",
    "chunk_text",
]
