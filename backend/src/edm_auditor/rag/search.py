"""Semantic search service."""

from .embeddings import EmbeddingProvider
from .models import SearchResult
from .vector_store import SQLiteVectorStore


class RAGSearch:
    """Embed a query and search the configured vector store."""

    def __init__(self, store: SQLiteVectorStore, provider: EmbeddingProvider) -> None:
        self.store = store
        self.provider = provider

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        threshold: float = 0.0,
        legal_act_id: int | None = None,
        rule_id: int | None = None,
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query must not be empty")
        vector = self.provider.embed_query(query)
        return self.store.search(
            vector,
            k=k,
            threshold=threshold,
            legal_act_id=legal_act_id,
            rule_id=rule_id,
        )
