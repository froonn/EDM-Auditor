"""Adapters for loading legal-act source files into the database."""

from collections.abc import Callable
from os import PathLike
from pathlib import Path

from edm_auditor.database.models import LegalAct
from edm_auditor.database.repositories import DocumentRepository
from sqlalchemy.orm import Session
from sqlalchemy import select

from edm_auditor.document_parser import DocumentParserService


class TextLegalActIngestor:
    """Parse a UTF-8 text file and create a ``LegalAct`` record."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        parser: DocumentParserService | None = None,
    ) -> None:
        self._repository = DocumentRepository(session_factory)
        self._parser = parser or DocumentParserService()

    def ingest(
        self,
        source: str | PathLike[str],
        *,
        code: str,
        title: str,
        number: str | None = None,
        source_url: str | None = None,
    ) -> LegalAct:
        path = Path(source)
        parsed = self._parser.parse(path)
        if parsed.source.format != "txt":
            raise ValueError("TextLegalActIngestor accepts only .txt files")
        return self._repository.create_legal_act(
            code=code,
            title=title,
            number=number,
            article_text=parsed.text,
            source_url=source_url,
        )


class DatabaseIndexSourceLoader:
    """Convert legal acts and their active rules into index sources."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def load(self) -> list["IndexSource"]:
        from .indexer import IndexSource

        with self._session_factory() as session:
            acts = session.scalars(select(LegalAct).order_by(LegalAct.id)).all()
            sources: list[IndexSource] = []
            for act in acts:
                sources.append(IndexSource(legal_act_id=act.id, text=act.article_text))
                for rule in sorted(
                    (rule for rule in act.rules if rule.is_active),
                    key=lambda item: item.id,
                ):
                    rule_context = "\n\n".join(
                        part
                        for part in (act.title, rule.name, rule.description, act.article_text)
                        if part
                    )
                    sources.append(
                        IndexSource(
                            legal_act_id=act.id,
                            rule_id=rule.id,
                            text=rule_context,
                        )
                    )
            return sources
