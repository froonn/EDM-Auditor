import json
from pathlib import Path

import pytest
from sqlalchemy import select

from edm_auditor.audit_engine import (
    AuditEngine,
    LLMInterpreter,
    AuditPersistence,
    RuleSpec,
    extract_entities,
)
from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.enums import AuditSeverity, CheckType, DocumentStatus
from edm_auditor.database.models import AuditReport, AuditRule, Base, Document
from edm_auditor.model_providers import StubLLMProvider


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
            rule_id=2,
            rule_code="other-document",
            name="Not applicable",
            severity="high",
            check_type="keyword",
            document_type="order",
            parameters={"keywords": ["отпуск"]},
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

    result = AuditEngine().audit(text, rules, document_type="contract")

    assert len(result.findings) == 1
    assert result.findings[0].quote == "14 дней"
    assert result.findings[0].deduplication_key
    assert result.diagnostics == ()


def test_invalid_rule_is_reported_without_hiding_other_findings() -> None:
    result = AuditEngine().audit(
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
    result = AuditEngine().audit(
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


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def test_persistence_creates_atomic_report_and_updates_status(session_factory) -> None:
    with session_factory.begin() as session:
        session.add(
            Document(
                title="Contract",
                file_type="txt",
                file_path="contract.txt",
                raw_text="Отпуск составляет 14 дней.",
                classified_type="contract",
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
                document_type="contract",
            )
        )

    report = AuditPersistence(session_factory).audit_document(document_id)

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
                classified_type="contract",
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
                    document_type="contract",
                ),
                AuditRule(
                    rule_code="probation-limit",
                    name="Probation limit",
                    severity=AuditSeverity.HIGH.value,
                    check_type=CheckType.DURATION.value,
                    parameters_json=json.dumps({"max_days": 90}),
                    document_type="contract",
                ),
                AuditRule(
                    rule_code="contract-date",
                    name="Contract date",
                    severity=AuditSeverity.MEDIUM.value,
                    check_type=CheckType.DATE.value,
                    parameters_json=json.dumps({"after": "2026-03-01"}),
                    document_type="contract",
                ),
                AuditRule(
                    rule_code="prohibited-probation-wording",
                    name="Prohibited probation wording",
                    severity=AuditSeverity.LOW.value,
                    check_type=CheckType.KEYWORD.value,
                    parameters_json=json.dumps({"keywords": ["испытательный срок"]}),
                    document_type="contract",
                ),
            ]
        )

    report = AuditPersistence(session_factory).audit_document(document_id)

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
        )
        session.add(document)
        session.flush()
        session.add(
            AuditRule(
                rule_code="condition-present",
                name="Condition",
                severity=AuditSeverity.LOW.value,
                check_type=CheckType.KEYWORD.value,
                parameters_json=json.dumps({"keywords": ["условие"]}),
            )
        )
        document_id = document.id

    report = AuditPersistence(
        session_factory,
        neural_interpreter=LLMInterpreter(StubLLMProvider()),
        neural_mode="best-effort",
    ).audit_document(document_id)

    summary = json.loads(report.summary)
    assert summary["neural"]["status"] == "completed"
    assert summary["neural"]["model"] == "stub-v1"
