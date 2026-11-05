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
from edm_auditor.database.enums import AuditSeverity, CheckType, DocumentStatus
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
            rule_code="leave-keyword",
            name="Missing leave wording",
            severity="medium",
            check_type="keyword",
            parameters={"keywords": ["14 дней"]},
        ),
        RuleSpec(
            rule_id=3,
            rule_code="inactive",
            name="Inactive",
            severity="critical",
            check_type="keyword",
            parameters={"keywords": ["отпуск"]},
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
        "Условие присутствует.",
        [
            RuleSpec(
                rule_id=1,
                rule_code="broken",
                name="Broken",
                severity="high",
                check_type="regex",
                parameters={"pattern": "["},
            ),
            RuleSpec(
                rule_id=2,
                rule_code="valid",
                name="Valid",
                severity="low",
                check_type="keyword",
                parameters={"keywords": ["условие"]},
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
                name="Minimum leave",
                severity="high",
                check_type="numeric",
                parameters={"entity": "duration", "min": 24},
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
                name="Minimum compensation",
                severity="high",
                check_type="numeric",
                parameters={"entity": "money", "min": 50},
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
                name="Minimum leave",
                severity="high",
                check_type="duration",
                parameters={"min_days": 24},
            )
        ],
    )

    assert result.findings[0].quote == "14 календарных дней"


def test_remote_work_gold_documents_report_findings_without_external_models() -> None:
    examples = Path(__file__).parents[2] / "examples"
    agreement = (examples / "remote_work_agreement.txt").read_text(encoding="utf-8")
    rules = (
        RuleSpec(
            rule_id=1,
            rule_code="minimum-compensation",
            name="Minimum compensation",
            severity="critical",
            check_type="numeric",
            parameters={"entity": "money", "min": 50},
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
                name="Leave duration",
                severity=AuditSeverity.HIGH.value,
                check_type=CheckType.KEYWORD.value,
                parameters_json=json.dumps({"keywords": ["14 дней"]}),
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
                    name="Minimum annual leave",
                    severity=AuditSeverity.HIGH.value,
                    check_type=CheckType.DURATION.value,
                    parameters_json=json.dumps({"min_days": 24}),
                    applicability_scope="typed",
                document_types=[_contract_type(session)],
                ),
                AuditRule(
                    rule_code="probation-limit",
                    name="Probation limit",
                    severity=AuditSeverity.HIGH.value,
                    check_type=CheckType.DURATION.value,
                    parameters_json=json.dumps({"max_days": 90}),
                    applicability_scope="typed",
                document_types=[_contract_type(session)],
                ),
                AuditRule(
                    rule_code="contract-date",
                    name="Contract date",
                    severity=AuditSeverity.MEDIUM.value,
                    check_type=CheckType.DATE.value,
                    parameters_json=json.dumps({"after": "2026-03-01"}),
                    applicability_scope="typed",
                document_types=[_contract_type(session)],
                ),
                AuditRule(
                    rule_code="prohibited-probation-wording",
                    name="Prohibited probation wording",
                    severity=AuditSeverity.LOW.value,
                    check_type=CheckType.KEYWORD.value,
                    parameters_json=json.dumps({"keywords": ["испытательный срок"]}),
                    applicability_scope="typed",
                document_types=[_contract_type(session)],
                ),
            ]
        )

    report = make_persistence(session_factory).audit_document(document_id)

    assert report.total_findings == 4
    assert report.high_count == 2
    assert report.medium_count == 1
    assert report.low_count == 1
    with session_factory() as session:
        stored = session.scalar(select(AuditReport).where(AuditReport.id == report.id))
        assert stored is not None
        assert {finding.quote for finding in stored.findings} == {
            "14 дней",
            "4 месяца",
            "01.02.2026",
            "испытательный срок",
        }


def test_persistence_stores_neural_analysis_status(session_factory) -> None:
    with session_factory.begin() as session:
        document = Document(
            title="Neural contract",
            file_type="txt",
            file_path="neural.txt",
            raw_text="Условие присутствует.",
            confirmed_types=[_contract_type(session)],
        )
        session.add(document)
        session.flush()
        session.add(
            AuditRule(
                rule_code="condition-present",
                name="Condition",
                severity=AuditSeverity.LOW.value,
                check_type=CheckType.KEYWORD.value,
                applicability_scope="universal",
                parameters_json=json.dumps({"keywords": ["условие"]}),
            )
        )
        document_id = document.id

    report = make_persistence(session_factory).audit_document(document_id)

    summary = json.loads(report.summary)
    assert summary["neural"]["status"] == "completed"
    assert summary["neural"]["model"] == "fake-llm"


def _universal_rule(keyword: str = "отсутствует") -> AuditRule:
    return AuditRule(
        rule_code=f"universal-{keyword}",
        name="Universal",
        severity=AuditSeverity.LOW.value,
        check_type=CheckType.KEYWORD.value,
        applicability_scope="universal",
        parameters_json=json.dumps({"keywords": [keyword]}),
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
        session.add(_universal_rule())
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
        session.add(_universal_rule())

    with pytest.raises(AuditModelError, match=message):
        make_persistence(session_factory, **options).audit_document(document_id)

    with session_factory() as session:
        assert session.get(Document, document_id).status == DocumentStatus.ERROR.value
        assert session.scalar(select(AuditReport)) is None


def test_embedding_failure_stops_semantic_audit() -> None:
    class FailingSearcher:
        def search(self, query, **kwargs):
            raise EmbeddingError("embedding service unavailable")

    engine = AuditEngine(entity_extractor=no_entities, rag_searcher=FailingSearcher())

    with pytest.raises(AuditModelError, match="semantic search failed"):
        engine.audit(
            "Отпуск 14 дней.",
            [
                RuleSpec(
                    rule_id=1,
                    rule_code="leave-context",
                    name="Leave context",
                    severity="medium",
                    check_type="semantic",
                    parameters={"query": "отпуск"},
                )
            ],
        )


def test_audit_runs_only_the_rules_chosen_by_the_resolver(session_factory) -> None:
    document_id = _stored_document(session_factory)
    other = DocumentType(code="payroll_order", name="Payroll")
    with session_factory.begin() as session:
        session.add(
            AuditRule(
                rule_code="other-type",
                name="Other type",
                severity=AuditSeverity.HIGH.value,
                check_type=CheckType.KEYWORD.value,
                applicability_scope="typed",
                document_types=[other],
                parameters_json=json.dumps({"keywords": ["отпуск"]}),
            )
        )
        session.add(_universal_rule("14 дней"))

    report = make_persistence(session_factory).audit_document(document_id)

    assert report.total_findings == 1
    assert report.findings[0].quote == "14 дней"


def test_preview_and_audit_use_the_same_rules(session_factory) -> None:
    document_id = _stored_document(session_factory)
    with session_factory.begin() as session:
        kept, excluded = _universal_rule("14 дней"), _universal_rule("отпуск")
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
        session.add_all([document, _universal_rule("Текст")])
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
        session.add(_universal_rule("14 дней"))

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
            name="Payroll",
            severity=AuditSeverity.HIGH.value,
            check_type=CheckType.KEYWORD.value,
            applicability_scope="typed",
            document_types=[other],
            parameters_json=json.dumps({"keywords": ["отпуск"]}),
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
