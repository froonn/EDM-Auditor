from pathlib import Path

import pytest
from sqlalchemy import select

from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import Base, LegalAct
from edm_auditor.rag import TextLegalActIngestor


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
