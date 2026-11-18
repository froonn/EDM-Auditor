import json
from pathlib import Path

import pytest
from sqlalchemy import select

from edm_auditor.applicability import (
    RagCandidate,
    ResolutionStatus,
    SelectionConfig,
    SelectionWarning,
)
from edm_auditor.audit_engine.extractors import entities_from_provider
from edm_auditor.audit_engine.neural_errors import DocumentTooLargeForAudit
from edm_auditor.audit_engine import (
    AuditEngine,
    AuditSelectionRequired,
    ChunkedEntityExtractor,
    LLMInterpreter,
    AuditPersistence,
    RuleSpec,
    extract_entities,
)
from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.enums import AuditSeverity, DocumentStatus
from edm_auditor.database.models import (
    AuditReport,
    AuditRule,
    Base,
    Document,
    DocumentType,
)
from edm_auditor.audit_engine.neural_errors import AuditModelError
from edm_auditor.rag.exceptions import EmbeddingError
from fakes import FailingEntityProvider, FailingLLMProvider, FakeLLMProvider, no_entities


def test_extract_entities_preserves_source_ranges() -> None:
    text = "Отпуск составляет 14 дней и выплата 500 BYN."

    entities = extract_entities(text, ("duration", "money"))

    assert [(item.kind, item.value) for item in entities] == [
        ("duration", "14 дней"),
        ("money", "500 BYN"),
    ]
    assert all(text[item.start_char : item.end_char] == item.value for item in entities)


def test_engine_applies_active_matching_rules_and_deduplicates() -> None:
    text = "Работнику предоставляется отпуск 14 дней."
    rules = [
        RuleSpec(
            rule_id=1,
            rule_code="leave-minimum",
            subject="Продолжительность отпуска",
            constraint_text="Отпуск должен быть не менее 24 дней.",
            constraint_json={"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
            severity="medium",
        ),
        RuleSpec(
            rule_id=3,
            rule_code="inactive",
            subject="Неактивное правило",
            constraint_text="Отпуск не менее 30 дней.",
            constraint_json={"kind": "value", "operator": "gte", "value": 30, "unit": "day"},
            severity="critical",
            is_active=False,
        ),
    ]

    result = AuditEngine(entity_extractor=no_entities).audit(text, rules)

    assert len(result.findings) == 1
    assert result.findings[0].quote == "14 дней"
    assert result.findings[0].deduplication_key
    assert result.diagnostics == ()


def test_invalid_rule_is_reported_without_hiding_other_findings() -> None:
    result = AuditEngine(entity_extractor=no_entities).audit(
        "Отпуск составляет 14 дней.",
        [
            RuleSpec(
                rule_id=1,
                rule_code="broken",
                subject="Broken",
                constraint_text="Broken constraint",
                constraint_json={"kind": "unknown"},
                severity="high",
            ),
            RuleSpec(
                rule_id=2,
                rule_code="valid",
                subject="Valid",
                constraint_text="Отпуск не менее 24 дней.",
                constraint_json={"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
                severity="low",
            ),
        ],
    )

    assert [finding.rule_code for finding in result.findings] == ["valid"]
    assert result.diagnostics[0].rule_code == "broken"


def test_numeric_rule_reports_values_outside_bounds() -> None:
    result = AuditEngine(entity_extractor=no_entities).audit(
        "Отпуск составляет 14 дней.",
        [
            RuleSpec(
                rule_id=4,
                rule_code="minimum-leave",
                subject="Minimum leave",
                constraint_text="Отпуск не менее 24 дней.",
                constraint_json={"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
                severity="high",
            )
        ],
    )

    assert result.findings[0].quote == "14 дней"


def test_engine_keeps_deterministic_entities_when_provider_returns_none() -> None:
    result = AuditEngine(entity_extractor=lambda _: ()).audit(
        "Компенсация составляет 35 рублей.",
        [
            RuleSpec(
                rule_id=5,
                rule_code="minimum-compensation",
                subject="Minimum compensation",
                constraint_text="Компенсация не менее 50 рублей.",
                constraint_json={"kind": "value", "operator": "gte", "value": 50, "unit": "byn"},
                severity="high",
            )
        ],
    )

    assert result.findings[0].quote == "35 рублей"


def test_engine_unions_provider_entities_with_deterministic_entities() -> None:
    result = AuditEngine(
        entity_extractor=lambda _: ({"kind": "duration", "value": "14 календарных дней"},)
    ).audit(
        "Отпуск 14 календарных дней.",
        [
            RuleSpec(
                rule_id=6,
                rule_code="minimum-leave",
                subject="Minimum leave",
                constraint_text="Отпуск не менее 24 дней.",
                constraint_json={"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
                severity="high",
            )
        ],
    )

    assert result.findings[0].quote == "14 календарных дней"


def test_remote_work_gold_documents_report_findings_without_external_models() -> None:
    corpus_docs = Path(__file__).parents[2] / "evaluation" / "corpus" / "documents"
    agreement = (corpus_docs / "remote_violating.txt").read_text(encoding="utf-8")
    rules = (
        RuleSpec(
            rule_id=1,
            rule_code="minimum-compensation",
            subject="Minimum compensation",
            constraint_text="Компенсация не менее 50 рублей.",
            constraint_json={"kind": "value", "operator": "gte", "value": 50, "unit": "byn"},
            severity="critical",
        ),
    )

    result = AuditEngine(entity_extractor=no_entities).audit(agreement, rules)

    assert result.findings


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _contract_type(session) -> DocumentType:
    return session.get(DocumentType, "contract") or DocumentType(
        code="contract", name="Contract"
    )


def make_persistence(session_factory, *, llm=None, entity_extractor=no_entities):
    return AuditPersistence(
        session_factory,
        engine=AuditEngine(entity_extractor=entity_extractor),
        neural_interpreter=LLMInterpreter(llm or FakeLLMProvider()),
    )


def test_persistence_creates_atomic_report_and_updates_status(session_factory) -> None:
    with session_factory.begin() as session:
        session.add(
            Document(
                title="Contract",
                file_type="txt",
                file_path="contract.txt",
                raw_text="Отпуск составляет 14 дней.",
                confirmed_types=[_contract_type(session)],
            )
        )
    with session_factory() as session:
        document_id = session.scalar(select(Document.id))
    with session_factory.begin() as session:
        session.add(
            AuditRule(
                rule_code="leave-days",
                subject="Leave duration",
                constraint_text="Отпуск не менее 24 дней.",
                constraint_json=json.dumps(
                    {"kind": "value", "operator": "gte", "value": 24, "unit": "day"}
                ),
                severity=AuditSeverity.HIGH.value,
                applicability_scope="typed",
                document_types=[_contract_type(session)],
            )
        )

    report = make_persistence(session_factory).audit_document(document_id)

    assert report.total_findings == 1
    with session_factory() as session:
        document = session.get(Document, document_id)
        stored = session.scalar(select(AuditReport).where(AuditReport.id == report.id))
        assert document.status == DocumentStatus.AUDITED.value
        assert stored is not None
        assert len(stored.findings) == 1


def test_persistence_audits_synthetic_employment_contract(session_factory) -> None:
    contract = (
        Path(__file__).parents[1] / "fixtures" / "employment_contract.txt"
    ).read_text(encoding="utf-8")
    with session_factory.begin() as session:
        session.add(
            Document(
                title="Synthetic employment contract",
                file_type="txt",
                file_path="employment_contract.txt",
                raw_text=contract,
                confirmed_types=[_contract_type(session)],
            )
        )
    with session_factory() as session:
        document_id = session.scalar(select(Document.id))
    with session_factory.begin() as session:
        session.add_all(
            [
                AuditRule(
                    rule_code="leave-minimum",
                    subject="Minimum annual leave",
                    constraint_text="Отпуск не менее 24 дней.",
                    constraint_json=json.dumps(
                        {"kind": "value", "operator": "gte", "value": 24, "unit": "day"}
                    ),
                    severity=AuditSeverity.HIGH.value,
                    applicability_scope="typed",
                    document_types=[_contract_type(session)],
                ),
                AuditRule(
                    rule_code="probation-limit",
                    subject="Probation limit",
                    constraint_text="Испытательный срок не более 90 дней.",
                    constraint_json=json.dumps(
                        {"kind": "value", "operator": "lte", "value": 90, "unit": "day"}
                    ),
                    severity=AuditSeverity.HIGH.value,
                    applicability_scope="typed",
                    document_types=[_contract_type(session)],
                ),
            ]
        )

    report = make_persistence(session_factory).audit_document(document_id)

    assert report.total_findings == 2
    assert report.high_count == 2
    with session_factory() as session:
        stored = session.scalar(select(AuditReport).where(AuditReport.id == report.id))
        assert stored is not None
        assert {finding.quote for finding in stored.findings} == {"14 дней", "4 месяца"}


def test_persistence_stores_neural_analysis_status(session_factory) -> None:
    with session_factory.begin() as session:
        document = Document(
            title="Neural contract",
            file_type="txt",
            file_path="neural.txt",
            raw_text="Отпуск составляет 14 дней.",
            confirmed_types=[_contract_type(session)],
        )
        session.add(document)
        session.flush()
        session.add(
            AuditRule(
                rule_code="condition-present",
                subject="Condition",
                constraint_text="Отпуск не менее 24 дней.",
                constraint_json=json.dumps(
                    {"kind": "value", "operator": "gte", "value": 24, "unit": "day"}
                ),
                severity=AuditSeverity.LOW.value,
                applicability_scope="universal",
            )
        )
        document_id = document.id

    report = make_persistence(session_factory).audit_document(document_id)

    summary = json.loads(report.summary)
    assert summary["neural"]["status"] == "completed"
    assert summary["neural"]["model"] == "fake-llm"


def _universal_rule(min_days: int = 10) -> AuditRule:
    return AuditRule(
        rule_code=f"universal-{min_days}",
        subject=f"Universal {min_days}",
        constraint_text=f"Срок не менее {min_days} дней.",
        constraint_json=json.dumps(
            {"kind": "value", "operator": "gte", "value": min_days, "unit": "day"}
        ),
        severity=AuditSeverity.LOW.value,
        applicability_scope="universal",
    )


def _stored_document(session_factory) -> int:
    with session_factory.begin() as session:
        document = Document(
            title="Contract",
            file_type="txt",
            file_path="contract.txt",
            raw_text="Отпуск составляет 14 дней.",
            confirmed_types=[_contract_type(session)],
        )
        session.add(document)
        session.flush()
        return document.id


def test_persistence_calls_llm_even_without_findings(session_factory) -> None:
    document_id = _stored_document(session_factory)
    with session_factory.begin() as session:
        session.add(_universal_rule(10))
    llm = FakeLLMProvider()

    report = make_persistence(session_factory, llm=llm).audit_document(document_id)

    assert report.total_findings == 0
    assert len(llm.prompts) == 1
    assert json.loads(report.summary)["neural"]["general_summary"] == "Reviewed."


@pytest.mark.parametrize(
    "options, message",
    [
        ({"llm": FailingLLMProvider()}, "LLM analysis failed"),
        (
            {"entity_extractor": lambda text: FailingEntityProvider().extract(text)},
            "entity extraction model failed",
        ),
    ],
)
def test_model_failure_marks_document_failed_without_report(
    session_factory, options, message
) -> None:
    document_id = _stored_document(session_factory)
    with session_factory.begin() as session:
        session.add(_universal_rule(10))

    with pytest.raises(AuditModelError, match=message):
        make_persistence(session_factory, **options).audit_document(document_id)

    with session_factory() as session:
        assert session.get(Document, document_id).status == DocumentStatus.ERROR.value
        assert session.scalar(select(AuditReport)) is None


def test_audit_runs_only_the_rules_chosen_by_the_resolver(session_factory) -> None:
    document_id = _stored_document(session_factory)
    other = DocumentType(code="payroll_order", name="Payroll")
    with session_factory.begin() as session:
        session.add(
            AuditRule(
                rule_code="other-type",
                subject="Other type",
                constraint_text="Отпуск не менее 30 дней.",
                constraint_json=json.dumps(
                    {"kind": "value", "operator": "gte", "value": 30, "unit": "day"}
                ),
                severity=AuditSeverity.HIGH.value,
                applicability_scope="typed",
                document_types=[other],
            )
        )
        session.add(_universal_rule(24))

    report = make_persistence(session_factory).audit_document(document_id)

    assert report.total_findings == 1
    assert report.findings[0].quote == "14 дней"


def test_preview_and_audit_use_the_same_rules(session_factory) -> None:
    document_id = _stored_document(session_factory)
    with session_factory.begin() as session:
        kept, excluded = _universal_rule(24), _universal_rule(30)
        session.add_all([kept, excluded])
        session.flush()
        kept_id, excluded_id = kept.id, excluded.id
    selection = SelectionConfig(excluded_rule_ids=frozenset({excluded_id}))
    persistence = make_persistence(session_factory)

    preview = persistence.preview(document_id, selection)
    report = persistence.audit_document(document_id, selection)

    assert preview.selected_rule_ids == (kept_id,)
    assert {finding.rule_id for finding in report.findings} == {kept_id}
    with session_factory() as session:
        assert session.get(Document, document_id).status == DocumentStatus.AUDITED.value


def test_unconfigured_audit_keeps_document_status_and_creates_no_report(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        document = Document(
            title="Unknown", file_type="txt", file_path="u.txt", raw_text="Текст."
        )
        session.add_all([document, _universal_rule(24)])
        session.flush()
        document_id = document.id

    with pytest.raises(AuditSelectionRequired) as error:
        make_persistence(session_factory).audit_document(document_id)

    assert error.value.resolution.status is ResolutionStatus.NEEDS_CONFIGURATION
    with session_factory() as session:
        assert session.get(Document, document_id).status == DocumentStatus.UPLOADED.value
        assert session.scalar(select(AuditReport)) is None


def test_audit_continues_with_a_warning_when_rag_is_unavailable(session_factory) -> None:
    document_id = _stored_document(session_factory)
    with session_factory.begin() as session:
        session.add(_universal_rule(24))

    def failing_recommender(_: str):
        raise EmbeddingError("embedding service unavailable")

    persistence = AuditPersistence(
        session_factory,
        engine=AuditEngine(entity_extractor=no_entities),
        neural_interpreter=LLMInterpreter(FakeLLMProvider()),
        rag_recommender=failing_recommender,
    )

    preview = persistence.preview(document_id)
    report = persistence.audit_document(document_id)

    assert SelectionWarning.RAG_UNAVAILABLE in preview.warnings
    assert report.total_findings == 1


def test_rag_candidate_of_another_act_does_not_select_its_rule(session_factory) -> None:
    document_id = _stored_document(session_factory)
    other = DocumentType(code="payroll_order", name="Payroll")
    with session_factory.begin() as session:
        rule = AuditRule(
            rule_code="payroll",
            subject="Payroll",
            constraint_text="Срок не менее 24 дней.",
            constraint_json=json.dumps(
                {"kind": "value", "operator": "gte", "value": 24, "unit": "day"}
            ),
            severity=AuditSeverity.HIGH.value,
            applicability_scope="typed",
            document_types=[other],
        )
        session.add(rule)
        session.flush()
        rule_id = rule.id
    persistence = AuditPersistence(
        session_factory,
        engine=AuditEngine(entity_extractor=no_entities),
        neural_interpreter=LLMInterpreter(FakeLLMProvider()),
        rag_recommender=lambda _: [RagCandidate(5, rule_id, 0.99, 0.5)],
    )

    preview = persistence.preview(document_id)

    assert preview.status is ResolutionStatus.NO_APPLICABLE_RULES
    assert preview.recommendations[0].rule_id == rule_id


class _ChunkProvider:
    model_name = "chunk-extractor"

    def __init__(self, *values: str) -> None:
        self.values = values
        self.chunks: list[str] = []

    def extract(self, text: str):
        self.chunks.append(text)
        return [
            {"kind": "duration", "value": value} for value in self.values if value in text
        ]


def test_entity_extractor_reads_the_whole_document_in_limited_parts() -> None:
    first = "В начале срок 24 дня."
    last = "В конце срок 36 дней."
    text = "\n".join([first, *["Обычная строка без значений."] * 100, last])
    provider = _ChunkProvider("24 дня", "36 дней")

    entities = ChunkedEntityExtractor(provider, max_chars=300, overlap_chars=0)(text)

    assert len(provider.chunks) > 1
    assert all(len(chunk) <= 300 for chunk in provider.chunks)
    assert [text[item.start_char : item.end_char] for item in entities] == ["24 дня", "36 дней"]


def test_entity_extractor_counts_an_overlapping_value_once() -> None:
    text = "\n".join(["Срок 24 дня.", "Строка.", "Строка."])
    provider = _ChunkProvider("24 дня")

    entities = ChunkedEntityExtractor(provider, max_chars=20, overlap_chars=15)(text)

    assert len(provider.chunks) > 1
    assert len(entities) == 1


def test_entity_extractor_refuses_before_calling_the_model() -> None:
    provider = _ChunkProvider()

    with pytest.raises(DocumentTooLargeForAudit):
        ChunkedEntityExtractor(provider, max_chars=10, overlap_chars=0, max_chunks=2)(
            "Первая строка.\nВторая строка.\nТретья строка."
        )

    assert provider.chunks == []


def test_too_large_document_is_not_reported_as_a_model_failure() -> None:
    def too_large(_: str):
        raise DocumentTooLargeForAudit("limit")

    with pytest.raises(DocumentTooLargeForAudit):
        AuditEngine(entity_extractor=too_large).audit("Текст", ())


def test_day_of_month_is_not_extracted_as_a_period() -> None:
    text = "Расчет производится 5 числа следующего месяца, срок договора 2 месяца."

    durations = [item.value for item in extract_entities(text) if item.kind == "duration"]

    assert durations == ["2 месяца"]


def test_day_of_month_from_the_model_is_not_a_period() -> None:
    text = "Расчет производится 5 числа следующего месяца."

    entities = entities_from_provider(
        text, [{"kind": "duration", "value": "5 числа следующего месяца"}]
    )

    assert entities == ()
