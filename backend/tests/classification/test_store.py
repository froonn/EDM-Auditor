import pytest
from sqlalchemy import select

from edm_auditor.classification import (
    ClassificationModelError,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    DocumentClassifier,
    TypeSuggestion,
)
from edm_auditor.classification.store import (
    DocumentClassificationService,
    document_type_options,
    ensure_default_document_types,
    override_classification,
    record_type_suggestion,
    store_classification,
    stored_classification,
)
from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import (
    Base,
    Document,
    DocumentType,
    DocumentTypeSuggestion,
)
from fakes import FailingClassificationProvider, FakeClassificationProvider

TRIP = ClassificationResult(
    ClassificationStatus.CLASSIFIED,
    confirmed_document_types=("business_trip_order",),
    confidence=0.9,
)


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
    return Document(title="Doc", file_type="txt", file_path="dir/doc.txt", raw_text=raw_text)


def _saved_document(session_factory) -> int:
    with session_factory.begin() as session:
        document = _document()
        session.add(document)
        session.flush()
        return document.id


def _service(session_factory, provider=None) -> DocumentClassificationService:
    return DocumentClassificationService(
        session_factory, DocumentClassifier(provider or FakeClassificationProvider())
    )


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
    document_id = _saved_document(session_factory)

    _service(session_factory).classify(document_id)

    with session_factory() as session:
        stored = session.get(Document, document_id)
        result = stored_classification(stored)
        assert stored.classified_type == "business_trip_order"
        assert result.status is ClassificationStatus.CLASSIFIED
        assert result.confirmed_document_types == ("business_trip_order",)
        assert result.source is ClassificationSource.LLM
        assert result.candidate_types[0].code == "business_trip_order"


def test_manual_override_has_priority_and_keeps_the_automatic_result(session_factory) -> None:
    with session_factory.begin() as session:
        document = _document()
        session.add(document)
        session.flush()
        store_classification(session, document, TRIP)
        result = override_classification(
            session, document, ["payroll_order", "vacation_order"]
        )
        assert result.source is ClassificationSource.MANUAL
        assert '"business_trip_order"' in document.classification_auto

        repeated = store_classification(session, document, TRIP)

        assert repeated.source is ClassificationSource.MANUAL
        assert repeated.confirmed_document_types == ("payroll_order", "vacation_order")


def test_empty_override_restores_the_automatic_result_without_the_model(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        document = _document()
        session.add(document)
        session.flush()
        store_classification(session, document, TRIP)
        override_classification(session, document, ["payroll_order"])

        result = override_classification(session, document, [])

        assert result.source is ClassificationSource.LLM
        assert result.confirmed_document_types == ("business_trip_order",)
        assert document.classification_source == "llm"


def test_empty_override_without_a_result_requests_classification_again(
    session_factory,
) -> None:
    document_id = _saved_document(session_factory)
    with session_factory.begin() as session:
        document = session.get(Document, document_id)
        override_classification(session, document, ["payroll_order"])
        override_classification(session, document, [])
        assert document.classification_status is None

    _service(session_factory).ensure_classified(document_id)

    with session_factory() as session:
        assert session.get(Document, document_id).classification_status == "classified"


def test_deactivated_type_is_not_offered_to_the_model(session_factory) -> None:
    with session_factory.begin() as session:
        session.get(DocumentType, "business_trip_order").is_active = False
    document_id = _saved_document(session_factory)
    provider = FakeClassificationProvider()

    result = _service(session_factory, provider).classify(document_id)

    assert result.status is ClassificationStatus.UNKNOWN
    assert "business_trip_order" not in {
        item.code for item in provider.requests[0]["document_types"]
    }
    assert provider.requests[0]["filename"] == "doc.txt"


def test_failure_marks_a_new_document_and_ensure_classified_retries(session_factory) -> None:
    document_id = _saved_document(session_factory)

    with pytest.raises(ClassificationModelError):
        _service(session_factory, FailingClassificationProvider()).classify(document_id)

    with session_factory() as session:
        assert session.get(Document, document_id).classification_status is None

    _service(session_factory).ensure_classified(document_id)

    with session_factory() as session:
        assert session.get(Document, document_id).classification_status == "classified"


def test_ensure_classified_does_not_repeat_a_finished_classification(session_factory) -> None:
    document_id = _saved_document(session_factory)
    provider = FakeClassificationProvider()
    service = _service(session_factory, provider)

    service.ensure_classified(document_id)
    service.ensure_classified(document_id)

    assert len(provider.requests) == 1


def test_unknown_document_is_reported(session_factory) -> None:
    with pytest.raises(LookupError):
        _service(session_factory).classify(999)


def test_catalog_options_carry_descriptions_for_the_model(session_factory) -> None:
    with session_factory() as session:
        options = {item.code: item for item in document_type_options(session)}

    assert options["vacation_order"].name == "Приказ об отпуске"
    assert options["vacation_order"].description


def test_suggestions_ignore_existing_types_and_count_repeats(session_factory) -> None:
    with session_factory.begin() as session:
        record_type_suggestion(session, TypeSuggestion("приказ  об ОТПУСКЕ"))
        record_type_suggestion(session, TypeSuggestion("Докладная записка", "Причина"))
        record_type_suggestion(session, TypeSuggestion("докладная  записка", "Другая"))

    with session_factory() as session:
        stored = session.scalars(select(DocumentTypeSuggestion)).all()
        assert [item.name for item in stored] == ["Докладная записка"]
        assert stored[0].occurrences == 2
        assert stored[0].reason == "Причина"
