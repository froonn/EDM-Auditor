"""Adapters for loading legal-act source files into the database."""

from collections.abc import Callable
from os import PathLike
from pathlib import Path

from edm_auditor.database.models import LegalAct
from edm_auditor.database.repositories import DocumentRepository
from sqlalchemy.orm import Session

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
