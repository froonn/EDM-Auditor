"""Command-line operations for the local RAG index."""

import argparse
import os
from pathlib import Path

from edm_auditor.database.config import DatabaseSettings
from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.model_config import ModelSettings
from edm_auditor.model_providers import create_embedding_provider

from .config import RAGSettings
from .indexer import RAGIndexer
from .ingestion import DatabaseIndexSourceLoader
from .search import RAGSearch
from .vector_store import SQLiteVectorStore


def _components():
    settings = RAGSettings.from_env()
    if "RAG_EMBEDDING_MODEL" in os.environ:
        from .embeddings import DeterministicEmbeddingProvider

        provider = DeterministicEmbeddingProvider(
            dimension=settings.embedding_dimension,
            model_name=settings.embedding_model,
        )
    else:
        provider = create_embedding_provider(ModelSettings.from_env().embedding)
    store = SQLiteVectorStore(
        settings.index_path,
        embedding_model=provider.model_name,
        dimension=provider.dimension,
        chunking_version="paragraph-v1",
    )
    database = DatabaseSettings(
        path=Path(os.getenv("EDM_DATABASE_PATH", "data/edm_auditor.sqlite3"))
    )
    return store, provider, create_session_factory(create_engine_for(database.url))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local EDM-Auditor RAG index")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="rebuild the index from legal acts")
    subparsers.add_parser("count", help="show the number of indexed chunks")
    search = subparsers.add_parser("search", help="search indexed legal text")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=5)
    search.add_argument("--threshold", type=float, default=0.0)
    args = parser.parse_args(argv)

    store, provider, session_factory = _components()
    if args.command == "build":
        count = RAGIndexer(store, provider).build(
            DatabaseIndexSourceLoader(session_factory).load()
        )
        print(f"indexed chunks: {count}")
    elif args.command == "count":
        print(f"indexed chunks: {store.count()}")
    else:
        results = RAGSearch(store, provider).search(
            args.query, k=args.k, threshold=args.threshold
        )
        for result in results:
            chunk = result.chunk
            print(
                f"{result.score:.4f} legal_act={chunk.legal_act_id} "
                f"rule={chunk.rule_id or 'base'} range={chunk.start_char}:{chunk.end_char}"
            )
            print(chunk.text)
    return 0
