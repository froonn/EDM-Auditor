from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import pytest

from edm_auditor.database.connection import create_engine_for, create_session_factory
from edm_auditor.database.models import (
    AuditFinding,
    AuditReport,
    AuditResolution,
    AuditRule,
    AuthAuditLog,
    Base,
    Document,
    DocumentParagraph,
    Group,
    GroupPermission,
    LegalAct,
    User,
    UserSession,
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
        "groups",
        "group_permissions",
        "user_groups",
        "user_sessions",
        "auth_audit_log",
        "document_types",
        "document_type_suggestions",
        "document_confirmed_types",
        "rule_document_types",
        "legal_act_document_types",
        "documents",
        "document_paragraphs",
        "document_statements",
        "legal_acts",
        "audit_rules",
        "audit_reports",
        "audit_findings",
        "audit_resolutions",
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
            subject="Linked rule",
            constraint_text="Linked constraint",
            severity="low",
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
                subject="Required title",
                constraint_text="Title is required",
                severity="low",
                constraint_json='{"kind": "value", "operator": "gte", "value": 1, "unit": "day"}',
            )
        )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                AuditRule(
                    rule_code="RULE-1",
                    subject="Duplicate",
                    constraint_text="Duplicate constraint",
                    severity="low",
                )
            )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                AuditRule(
                    rule_code="RULE-2",
                    subject="Invalid JSON",
                    constraint_text="Invalid JSON constraint",
                    severity="low",
                    constraint_json="{invalid",
                )
            )


def test_single_super_admin_and_group_constraints_are_enforced(session_factory) -> None:
    with session_factory.begin() as session:
        u1 = User(
            username="admin",
            email="admin@example.com",
            hashed_password="hash",
            is_super_admin=True,
        )
        u2 = User(
            username="user2",
            email="user2@example.com",
            hashed_password="hash",
            is_super_admin=False,
        )
        u3 = User(
            username="user3",
            email="user3@example.com",
            hashed_password="hash",
            is_super_admin=False,
        )
        session.add_all([u1, u2, u3])
        session.flush()
        # Same name 'admin' is allowed across distinct kinds (custom vs personal).
        session.add_all(
            [
                Group(name="admin", kind="custom"),
                Group(name="admin", kind="personal", owner_user_id=u1.id),
            ]
        )

    # Second super-admin violates the partial unique index.
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                User(
                    username="second-super",
                    email="second@example.com",
                    hashed_password="hash",
                    is_super_admin=True,
                )
            )

    # Personal group without owner_user_id violates check constraint.
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(Group(name="orphan", kind="personal", owner_user_id=None))

    # Duplicate (kind, name) violates unique constraint.
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(Group(name="admin", kind="custom"))


def test_audit_resolution_check_and_cascade(session_factory) -> None:
    with session_factory.begin() as session:
        report = AuditReport(
            document=Document(
                title="Contract",
                file_type="txt",
                file_path="contract.txt",
                raw_text="Body",
                status="audited",
            ),
            summary="{}",
        )
        session.add(report)
        session.flush()
        report_id = report.id
        session.add(
            AuditResolution(
                report_id=report_id,
                author_name="auditor",
                decision="approved",
                comment="Looks good",
            )
        )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                AuditResolution(
                    report_id=report_id,
                    author_name="auditor",
                    decision="invalid_decision",
                )
            )

    with session_factory.begin() as session:
        session.delete(session.get(AuditReport, report_id))

    with session_factory() as session:
        assert session.query(AuditResolution).count() == 0
        assert session.query(AuthAuditLog).count() == 0
        assert session.query(GroupPermission).count() == 0
        assert session.query(UserSession).count() == 0
