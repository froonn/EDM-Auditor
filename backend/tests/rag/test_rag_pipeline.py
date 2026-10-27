from pathlib import Path

import pytest

from edm_auditor.rag import (
    DeterministicEmbeddingProvider,
    IndexSource,
    RAGIndexer,
    RAGSearch,
    SQLiteVectorStore,
)
from edm_auditor.rag.exceptions import IndexConfigurationError


def test_index_and_search_are_repeatable(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider(dimension=8)
    store = SQLiteVectorStore(
        tmp_path / "vectors.sqlite3",
        embedding_model=provider.model_name,
        dimension=provider.dimension,
        chunking_version="paragraph-v1",
    )
    indexer = RAGIndexer(store, provider, max_chars=40, overlap_chars=5)
    sources = [IndexSource(legal_act_id=3, rule_id=9, text="Annual leave is granted every year.")]

    assert indexer.build(sources) == 1
    assert indexer.build(sources) == 1
    assert store.count() == 1

    results = RAGSearch(store, provider).search("Annual leave", k=1)

    assert len(results) == 1
    assert results[0].chunk.legal_act_id == 3
    assert results[0].chunk.rule_id == 9
    assert results[0].score > 0


def test_search_filters_by_source(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider(dimension=8)
    store = SQLiteVectorStore(
        tmp_path / "vectors.sqlite3",
        embedding_model=provider.model_name,
        dimension=provider.dimension,
        chunking_version="paragraph-v1",
    )
    RAGIndexer(store, provider).build(
        [
            IndexSource(legal_act_id=1, text="First act"),
            IndexSource(legal_act_id=2, text="Second act"),
        ]
    )

    results = RAGSearch(store, provider).search("act", legal_act_id=2)

    assert len(results) == 1
    assert results[0].chunk.legal_act_id == 2


def test_incompatible_index_configuration_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    SQLiteVectorStore(
        path,
        embedding_model="model-a",
        dimension=8,
        chunking_version="paragraph-v1",
    )
    with pytest.raises(IndexConfigurationError):
        SQLiteVectorStore(
            path,
            embedding_model="model-b",
            dimension=8,
            chunking_version="paragraph-v1",
        )


def test_rebuild_removes_stale_chunks(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider(dimension=8)
    store = SQLiteVectorStore(
        tmp_path / "vectors.sqlite3",
        embedding_model=provider.model_name,
        dimension=provider.dimension,
        chunking_version="paragraph-v1",
    )
    indexer = RAGIndexer(store, provider)

    indexer.build(
        [
            IndexSource(legal_act_id=1, text="First act"),
            IndexSource(legal_act_id=2, text="Second act"),
        ]
    )
    indexer.build([IndexSource(legal_act_id=1, text="Updated act")])

    assert store.count() == 1
    assert store.delete_legal_act(1) == 1
    assert store.count() == 0
