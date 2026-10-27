from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.enums import DocumentStatus
from edm_auditor.database.models import Base, Document
from edm_auditor.database.repositories import DocumentRepository
from edm_auditor.document_parser import (
    DocumentMetadata,
    ParsedDocument,
    ParsedParagraph,
)


@pytest.fixture
def repository():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield DocumentRepository(factory), factory
    finally:
        engine.dispose()


def parsed_document() -> ParsedDocument:
    return ParsedDocument(
        source=DocumentMetadata(
            filename="contract.pdf",
            media_type="application/pdf",
            size_bytes=20,
            format="pdf",
            processed_at=datetime.now(),
        ),
        text="First.\n\nSecond.",
        paragraphs=(
            ParsedParagraph(0, "First.", 0, 6, 1),
            ParsedParagraph(1, "Second.", 8, 15, 1),
        ),
    )


def test_save_and_load_parsed_document_preserves_parser_contract(repository) -> None:
    repo, _ = repository

    saved = repo.save_parsed_document(
        parsed_document(), title="Employment contract", file_path="/files/contract.pdf"
    )
    loaded = repo.get_document(saved.id)

    assert loaded is not None
    assert loaded.raw_text == "First.\n\nSecond."
    assert [(item.text, item.start_char, item.end_char, item.page_number) for item in loaded.paragraphs] == [
        ("First.", 0, 6, 1),
        ("Second.", 8, 15, 1),
    ]


def test_save_is_atomic_when_a_paragraph_is_invalid(repository) -> None:
    repo, factory = repository
    parsed = parsed_document()
    invalid = ParsedDocument(
        source=parsed.source,
        text=parsed.text,
        paragraphs=parsed.paragraphs
        + (ParsedParagraph(1, "duplicate", 0, 9, 1),),
    )

    with pytest.raises(IntegrityError):
        repo.save_parsed_document(invalid)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0


def test_update_status_rejects_missing_document(repository) -> None:
    repo, _ = repository

    with pytest.raises(LookupError):
        repo.update_status(999, DocumentStatus.PROCESSING)
