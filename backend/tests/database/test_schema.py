from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import pytest

from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import (
    AuditFinding,
    AuditReport,
    AuditRule,
    Base,
    Document,
    DocumentParagraph,
    LegalAct,
    User,
)


@pytest.fixture
def session_factory():
    engine = create_engine_for("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def test_schema_contains_all_tables(session_factory) -> None:
    engine = session_factory.kw["bind"]
    assert set(inspect(engine).get_table_names()) == {
        "users",
        "document_types",
        "document_confirmed_types",
        "rule_document_types",
        "legal_act_document_types",
        "documents",
        "document_paragraphs",
        "legal_acts",
        "audit_rules",
        "audit_reports",
        "audit_findings",
        "rule_extraction_results",
    }


def test_user_and_paragraph_uniqueness_is_enforced(session_factory) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                User(
                    username="auditor",
                    email="auditor@example.com",
                    hashed_password="hash",
                ),
                Document(
                    title="Contract",
                    file_type="pdf",
                    file_path="contract.pdf",
                ),
            ]
        )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                User(
                    username="auditor",
                    email="other@example.com",
                    hashed_password="hash",
                )
            )

    with session_factory.begin() as session:
        document = session.query(Document).one()
        session.add(
            DocumentParagraph(
                document_id=document.id,
                paragraph_index=0,
                text="Text",
                start_char=0,
                end_char=4,
            )
        )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                DocumentParagraph(
                    document_id=document.id,
                    paragraph_index=0,
                    text="Other",
                    start_char=0,
                    end_char=5,
                )
            )


def test_foreign_keys_and_document_cascade_are_enabled(session_factory) -> None:
    with session_factory.begin() as session:
        document = Document(
            title="Contract",
            file_type="docx",
            file_path="contract.docx",
            paragraphs=[
                DocumentParagraph(
                    paragraph_index=0,
                    text="Text",
                    start_char=0,
                    end_char=4,
                )
            ],
        )
        session.add(document)

    with session_factory.begin() as session:
        document = session.get(Document, document.id)
        session.delete(document)

    with session_factory() as session:
        assert session.query(DocumentParagraph).count() == 0


def test_legal_act_deletion_cascades_rules_and_nulls_findings(session_factory) -> None:
    with session_factory.begin() as session:
        legal_act = LegalAct(code="TK-RB", title="Labour Code", article_text="Article 1")
        rule = AuditRule(
            rule_code="RULE-LINKED",
            name="Linked rule",
            severity="low",
            check_type="keyword",
            legal_act=legal_act,
        )
        report = AuditReport(
            document=Document(
                title="Contract",
                file_type="txt",
                file_path="contract.txt",
                raw_text="Annual leave",
                status="audited",
            ),
            total_findings=1,
            summary="{}",
        )
        finding = AuditFinding(
            report=report,
            rule=rule,
            legal_act=legal_act,
            severity="low",
            description="Existing finding",
        )
        session.add_all([legal_act, rule, finding])
        session.flush()
        legal_act_id = legal_act.id
        rule_id = rule.id
        finding_id = finding.id

    with session_factory.begin() as session:
        session.delete(session.get(LegalAct, legal_act_id))

    with session_factory() as session:
        assert session.get(AuditRule, rule_id) is None
        finding = session.get(AuditFinding, finding_id)
        assert finding is not None
        assert finding.rule_id is None
        assert finding.legal_act_id is None


def test_rule_code_and_json_constraints_are_enforced(session_factory) -> None:
    with session_factory.begin() as session:
        session.add(
            AuditRule(
                rule_code="RULE-1",
                name="Required title",
                severity="low",
                check_type="keyword",
                parameters_json='{"keyword": "title"}',
            )
        )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                AuditRule(
                    rule_code="RULE-1",
                    name="Duplicate",
                    severity="low",
                    check_type="keyword",
                )
            )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                AuditRule(
                    rule_code="RULE-2",
                    name="Invalid JSON",
                    severity="low",
                    check_type="keyword",
                    parameters_json="{invalid",
                )
            )
