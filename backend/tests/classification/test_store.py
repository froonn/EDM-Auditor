import pytest
from sqlalchemy import select

from edm_auditor.classification import ClassificationSource, ClassificationStatus
from edm_auditor.classification.store import (
    classify_and_store,
    ensure_default_document_types,
    override_classification,
    stored_classification,
)
from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import Base, Document, DocumentType


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    ensure_default_document_types(factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _document(raw_text: str = "Приказ о направлении в командировку.\nОтчет о командировке.") -> Document:
    return Document(title="Doc", file_type="txt", file_path="doc.txt", raw_text=raw_text)


def test_catalog_defaults_are_idempotent_and_do_not_revive_deactivated_types(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        session.get(DocumentType, "payroll_order").is_active = False

    ensure_default_document_types(session_factory)

    with session_factory() as session:
        codes = session.scalars(select(DocumentType.code)).all()
        assert set(codes) == {
            "employment_contract",
            "business_trip_order",
            "remote_work_agreement",
            "payroll_order",
            "vacation_order",
        }
        assert session.get(DocumentType, "payroll_order").is_active is False


def test_classification_is_stored_on_the_document(session_factory) -> None:
    with session_factory.begin() as session:
        document = _document()
        session.add(document)
        session.flush()
        classify_and_store(session, document)
        document_id = document.id

    with session_factory() as session:
        stored = session.get(Document, document_id)
        result = stored_classification(stored)
        assert stored.classified_type == "business_trip_order"
        assert result.status is ClassificationStatus.CLASSIFIED
        assert result.confirmed_document_types == ("business_trip_order",)
        assert result.source is ClassificationSource.DETERMINISTIC
        assert result.candidate_types[0].code == "business_trip_order"


def test_manual_override_has_priority_and_keeps_the_automatic_result(session_factory) -> None:
    with session_factory.begin() as session:
        document = _document()
        session.add(document)
        session.flush()
        classify_and_store(session, document)
        result = override_classification(
            session, document, ["payroll_order", "vacation_order"]
        )
        assert result.source is ClassificationSource.MANUAL
        assert '"business_trip_order"' in document.classification_auto

        repeated = classify_and_store(session, document)

        assert repeated.source is ClassificationSource.MANUAL
        assert repeated.confirmed_document_types == ("payroll_order", "vacation_order")
        assert '"business_trip_order"' in document.classification_auto


def test_empty_override_restores_the_automatic_result(session_factory) -> None:
    with session_factory.begin() as session:
        document = _document()
        session.add(document)
        session.flush()
        override_classification(session, document, ["payroll_order"])

        result = override_classification(session, document, [])

        assert result.source is ClassificationSource.DETERMINISTIC
        assert result.confirmed_document_types == ("business_trip_order",)


def test_deactivated_type_is_not_used_by_the_classifier(session_factory) -> None:
    with session_factory.begin() as session:
        session.get(DocumentType, "business_trip_order").is_active = False
        document = _document()
        session.add(document)
        session.flush()

        result = classify_and_store(session, document)

    assert result.status is ClassificationStatus.UNKNOWN
