"""Persistence adapter for audit results."""

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from edm_auditor.database.enums import DocumentStatus
from edm_auditor.database.models import AuditFinding, AuditReport, AuditRule, Document

from .engine import AuditEngine
from .llm_interpreter import LLMInterpreter
from .models import FindingDraft, RuleSpec
from .neural_models import NeuralFinding, NeuralResult


class AuditPersistence:
    """Load a document, run the engine, and save one complete report."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        engine: AuditEngine | None = None,
        neural_interpreter: LLMInterpreter | None = None,
        neural_mode: str = "disabled",
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine or AuditEngine()
        if neural_mode not in {"disabled", "best-effort", "required"}:
            raise ValueError("neural_mode must be disabled, best-effort, or required")
        self._neural_interpreter = neural_interpreter
        self._neural_mode = neural_mode

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
                neural = self._analyze(result.findings, document.classified_type)
                counts = result.counts
                summary = {
                    "diagnostics": [
                        {"rule_code": item.rule_code, "message": item.message}
                        for item in result.diagnostics
                    ],
                    "rag_contexts": [
                        finding.source_context
                        for finding in result.findings
                        if finding.source_context is not None
                    ],
                    "neural": neural.as_dict(),
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

    def _analyze(
        self, findings: tuple[FindingDraft, ...], document_type: str | None
    ) -> NeuralResult:
        if self._neural_mode == "disabled":
            return NeuralResult(status="not_requested")
        if self._neural_interpreter is None:
            if self._neural_mode == "required":
                raise ValueError("neural analysis is required but not configured")
            return NeuralResult(
                status="failed", diagnostic="neural analysis is not configured"
            )
        neural_findings = tuple(
            NeuralFinding(
                key=_finding_key(finding),
                rule_code=finding.rule_code,
                severity=finding.severity,
                description=finding.description,
                quote=finding.quote,
                context=(
                    (finding.source_context,)
                    if finding.source_context is not None
                    else ()
                ),
            )
            for finding in findings
        )
        try:
            return self._neural_interpreter.analyze(
                neural_findings, document_type=document_type
            )
        except (RuntimeError, ValueError, TypeError) as exc:
            if self._neural_mode == "required":
                raise
            return NeuralResult(status="failed", diagnostic=str(exc)[:500])

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


def _finding_key(finding: FindingDraft) -> str:
    start = "" if finding.start_char is None else finding.start_char
    end = "" if finding.end_char is None else finding.end_char
    return f"{finding.rule_code}:{start}:{end}"
