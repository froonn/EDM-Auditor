"""Persistence adapter for audit results."""

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from edm_auditor.database.enums import DocumentStatus
from edm_auditor.database.models import AuditFinding, AuditReport, AuditRule, Document

from .engine import AuditEngine
from .models import RuleSpec


class AuditPersistence:
    """Load a document, run the engine, and save one complete report."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        engine: AuditEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine or AuditEngine()

    def audit_document(self, document_id: int) -> AuditReport:
        try:
            with self._session_factory.begin() as session:
                document = session.scalar(
                    select(Document)
                    .options(selectinload(Document.paragraphs))
                    .where(Document.id == document_id)
                )
                if document is None:
                    raise LookupError(f"Document {document_id} does not exist")
                document.status = DocumentStatus.PROCESSING.value
                session.flush()

                rules = session.scalars(
                    select(AuditRule)
                    .where(AuditRule.is_active.is_(True))
                    .order_by(AuditRule.id)
                ).all()
                result = self._engine.audit(
                    document.raw_text,
                    (_to_rule_spec(rule) for rule in rules),
                    document_type=document.classified_type,
                )
                counts = result.counts
                summary = {
                    "diagnostics": [
                        {"rule_code": item.rule_code, "message": item.message}
                        for item in result.diagnostics
                    ]
                }
                report = AuditReport(
                    document_id=document.id,
                    total_findings=len(result.findings),
                    critical_count=counts["critical"],
                    high_count=counts["high"],
                    medium_count=counts["medium"],
                    low_count=counts["low"],
                    summary=json.dumps(summary, ensure_ascii=False, sort_keys=True),
                )
                report.findings = [
                    AuditFinding(
                        rule_id=finding.rule_id,
                        legal_act_id=finding.legal_act_id,
                        severity=finding.severity,
                        description=finding.description,
                        start_char=finding.start_char,
                        end_char=finding.end_char,
                        quote=finding.quote,
                        recommendation=finding.recommendation,
                    )
                    for finding in result.findings
                ]
                session.add(report)
                document.status = DocumentStatus.AUDITED.value
                session.flush()
                return report
        except (LookupError, ValueError, TypeError, SQLAlchemyError):
            self._mark_error(document_id)
            raise

    def _mark_error(self, document_id: int) -> None:
        with self._session_factory.begin() as session:
            document = session.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.ERROR.value


def _to_rule_spec(rule: AuditRule) -> RuleSpec:
    parameters = json.loads(rule.parameters_json) if rule.parameters_json else {}
    if not isinstance(parameters, dict):
        raise ValueError(f"rule {rule.rule_code} parameters must be a JSON object")
    return RuleSpec(
        rule_id=rule.id,
        rule_code=rule.rule_code,
        name=rule.name,
        severity=rule.severity,
        check_type=rule.check_type,
        description=rule.description,
        document_type=rule.document_type,
        parameters=parameters,
        legal_act_id=rule.legal_act_id,
        is_active=rule.is_active,
    )
