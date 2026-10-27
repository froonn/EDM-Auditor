from pathlib import Path

import pytest
from sqlalchemy import select

from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import AuditRule, Base, LegalAct
from edm_auditor.database.enums import AuditSeverity, CheckType
from edm_auditor.database.repositories import DocumentRepository
from edm_auditor.rag import DatabaseIndexSourceLoader, TextLegalActIngestor


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def test_text_legal_act_ingestor_creates_legal_act(session_factory, tmp_path: Path) -> None:
    source = tmp_path / "labour-code.txt"
    source.write_text("Статья 1. Термины\n\nТекст статьи.", encoding="utf-8")

    legal_act = TextLegalActIngestor(session_factory).ingest(
        source,
        code="TK-RB",
        title="Трудовой кодекс Республики Беларусь",
        number="296-З",
        source_url="https://example.test/tk-rb",
    )

    assert legal_act.id is not None
    with session_factory() as session:
        stored = session.scalar(select(LegalAct).where(LegalAct.id == legal_act.id))
        assert stored is not None
        assert stored.article_text == "Статья 1. Термины\n\nТекст статьи."
        assert stored.code == "TK-RB"


def test_database_loader_returns_act_and_active_rule_sources(session_factory) -> None:
    repository = DocumentRepository(session_factory)
    act = repository.create_legal_act(
        code="TK-RB",
        title="Labour code",
        article_text="Article text",
    )
    repository.create_rule(
        rule_code="RULE-1",
        name="Active rule",
        description="Check article",
        severity=AuditSeverity.HIGH,
        check_type=CheckType.SEMANTIC,
        legal_act_id=act.id,
    )
    repository.create_rule(
        rule_code="RULE-2",
        name="Inactive rule",
        description="Do not index",
        severity=AuditSeverity.LOW,
        check_type=CheckType.KEYWORD,
        legal_act_id=act.id,
    )
    with session_factory.begin() as session:
        inactive = session.get(AuditRule, 2)
        assert inactive is not None
        inactive.is_active = False

    sources = DatabaseIndexSourceLoader(session_factory).load()

    assert len(sources) == 2
    assert sources[0].rule_id is None
    assert sources[1].rule_id == 1
    assert "Active rule" in sources[1].text
