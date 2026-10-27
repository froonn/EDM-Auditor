"""SQLite-backed local vector store."""

from collections.abc import Iterable
import json
from math import sqrt
from pathlib import Path
import sqlite3

from .exceptions import IndexConfigurationError, VectorStoreError
from .models import IndexMetadata, SearchResult, TextChunk


class SQLiteVectorStore:
    """Persist chunks and vectors in a local SQLite database."""

    def __init__(
        self,
        path: str | Path,
        *,
        embedding_model: str,
        dimension: int,
        chunking_version: str,
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.path = str(path)
        self.metadata = IndexMetadata(embedding_model, dimension, chunking_version)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS index_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS vectors "
                "(chunk_id TEXT PRIMARY KEY, legal_act_id INTEGER NOT NULL, "
                "rule_id INTEGER, text TEXT NOT NULL, chunk_index INTEGER NOT NULL, "
                "start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, "
                "chunking_version TEXT NOT NULL, vector TEXT NOT NULL)"
            )
            stored = dict(connection.execute("SELECT key, value FROM index_metadata"))
            expected = {
                "embedding_model": self.metadata.embedding_model,
                "dimension": str(self.metadata.dimension),
                "chunking_version": self.metadata.chunking_version,
            }
            if stored and stored != expected:
                raise IndexConfigurationError(
                    f"index metadata {stored} does not match expected {expected}"
                )
            connection.executemany(
                "INSERT OR REPLACE INTO index_metadata(key, value) VALUES (?, ?)",
                expected.items(),
            )

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])

    def clear(self) -> None:
        """Remove all entries from the index."""
        with self._connect() as connection:
            connection.execute("DELETE FROM vectors")

    def upsert(self, entries: Iterable[tuple[TextChunk, tuple[float, ...]]]) -> None:
        """Insert or replace entries with stable chunk IDs."""
        entries = tuple(entries)
        if any(len(vector) != self.metadata.dimension for _, vector in entries):
            raise VectorStoreError(f"all vectors must have dimension {self.metadata.dimension}")
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk.chunk_id,
                        chunk.legal_act_id,
                        chunk.rule_id,
                        chunk.text,
                        chunk.chunk_index,
                        chunk.start_char,
                        chunk.end_char,
                        chunk.chunking_version,
                        json.dumps(vector),
                    )
                    for chunk, vector in entries
                ],
            )

    def replace(self, entries: Iterable[tuple[TextChunk, tuple[float, ...]]]) -> None:
        entries = tuple(entries)
        if any(len(vector) != self.metadata.dimension for _, vector in entries):
            raise VectorStoreError(f"all vectors must have dimension {self.metadata.dimension}")
        with self._connect() as connection:
            connection.execute("DELETE FROM vectors")
            connection.executemany(
                "INSERT INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk.chunk_id,
                        chunk.legal_act_id,
                        chunk.rule_id,
                        chunk.text,
                        chunk.chunk_index,
                        chunk.start_char,
                        chunk.end_char,
                        chunk.chunking_version,
                        json.dumps(vector),
                    )
                    for chunk, vector in entries
                ],
            )

    def search(
        self,
        query_vector: tuple[float, ...],
        *,
        k: int = 5,
        threshold: float = 0.0,
        legal_act_id: int | None = None,
        rule_id: int | None = None,
    ) -> list[SearchResult]:
        if k <= 0:
            raise ValueError("k must be positive")
        if not -1.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between -1 and 1")
        if len(query_vector) != self.metadata.dimension:
            raise VectorStoreError(f"query vector must have dimension {self.metadata.dimension}")
        query_norm = sqrt(sum(value * value for value in query_vector))
        if query_norm == 0:
            raise VectorStoreError("query vector must not be zero")

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chunk_id, legal_act_id, rule_id, text, chunk_index, "
                "start_char, end_char, chunking_version, vector FROM vectors"
                " WHERE (? IS NULL OR legal_act_id = ?)"
                " AND (? IS NULL OR rule_id = ?)",
                (legal_act_id, legal_act_id, rule_id, rule_id),
            ).fetchall()
        results = []
        for row in rows:
            vector = tuple(json.loads(row[8]))
            norm = sqrt(sum(value * value for value in vector))
            score = (
                sum(left * right for left, right in zip(query_vector, vector)) / query_norm / norm
                if norm
                else 0.0
            )
            if score >= threshold:
                results.append(
                    SearchResult(
                        TextChunk(*row[:8]),
                        score,
                    )
                )
        return sorted(results, key=lambda result: (-result.score, result.chunk.chunk_id))[:k]
