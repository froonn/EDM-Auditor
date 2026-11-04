"""Persistence adapter for audit results."""

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
import logging
import sqlite3

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from edm_auditor.applicability import (
    DocumentContext,
    RagCandidate,
    ResolutionResult,
    ResolutionStatus,
    RuleApplicabilityResolver,
    SelectionConfig,
    SelectionWarning,
)
from edm_auditor.applicability.persistence import selection_snapshot
from edm_auditor.database.enums import DocumentStatus
from edm_auditor.database.models import (
    AuditFinding,
    AuditReport,
    AuditRule,
    Document,
    LegalAct,
)
from edm_auditor.rag.exceptions import RAGError

from .engine import AuditEngine
from .llm_interpreter import LLMInterpreter
from .models import FindingDraft, RuleSpec
from .neural_errors import AuditModelError
from .neural_models import NeuralFinding, NeuralResult


logger = logging.getLogger(__name__)


class AuditSelectionRequired(Exception):
    """The audit cannot run until the user resolves the rule selection."""

    def __init__(self, resolution: ResolutionResult) -> None:
        super().__init__(resolution.status.value)
        self.resolution = resolution


class AuditPersistence:
    """Load a document, run the engine, and save one complete report."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        engine: AuditEngine,
        neural_interpreter: LLMInterpreter,
        *,
        rag_recommender: Callable[[str], Sequence[RagCandidate]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine
        self._neural_interpreter = neural_interpreter
        self._rag_recommender = rag_recommender
        self._resolver = RuleApplicabilityResolver()

    def preview(
        self, document_id: int, selection: SelectionConfig | None = None
    ) -> ResolutionResult:
        """Resolve the same rule set that an audit with this selection would use."""
        with self._session_factory() as session:
            return self._resolve(session, self._load(session, document_id), selection)

    def audit_document(
        self, document_id: int, selection: SelectionConfig | None = None
    ) -> AuditReport:
        try:
            with self._session_factory.begin() as session:
                document = self._load(session, document_id)
                resolution = self._resolve(session, document, selection)
                if resolution.status is not ResolutionStatus.READY:
                    raise AuditSelectionRequired(resolution)
                document.status = DocumentStatus.PROCESSING.value
                session.flush()

                result = self._engine.audit(document.raw_text, resolution.selected_rules)
                neural = self._analyze(
                    result.findings,
                    ", ".join(item.code for item in document.confirmed_types) or None,
                )
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
                    "selection": selection_snapshot(
                        selection or SelectionConfig(),
                        _document_context(document),
                        resolution,
                        _applied_legal_acts(session, resolution),
                    ),
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
        except (LookupError, ValueError, TypeError, AuditModelError, SQLAlchemyError):
            self._mark_error(document_id)
            raise

    def _load(self, session: Session, document_id: int) -> Document:
        document = session.scalar(
            select(Document)
            .options(selectinload(Document.paragraphs))
            .where(Document.id == document_id)
        )
        if document is None:
            raise LookupError(f"Document {document_id} does not exist")
        return document

    def _resolve(
        self,
        session: Session,
        document: Document,
        selection: SelectionConfig | None,
    ) -> ResolutionResult:
        rules = session.scalars(
            select(AuditRule)
            .options(selectinload(AuditRule.document_types))
            .order_by(AuditRule.id)
        ).all()
        context = _document_context(document)
        rag_candidates, rag_failed = self._recommend(document.raw_text)
        resolution = self._resolver.resolve(
            map(_to_rule_spec, rules), context, selection, rag_candidates=rag_candidates
        )
        if rag_failed:
            resolution = replace(
                resolution,
                warnings=(*resolution.warnings, SelectionWarning.RAG_UNAVAILABLE),
            )
        return resolution

    def _recommend(self, text: str) -> tuple[Sequence[RagCandidate], bool]:
        """RAG only informs the selection, so its failure must not stop deterministic checks."""
        if self._rag_recommender is None:
            return (), False
        try:
            return self._rag_recommender(text), False
        except (RuntimeError, ValueError, TypeError, RAGError, sqlite3.Error) as exc:
            logger.warning("RAG recommendations are unavailable: %s", type(exc).__name__)
            return (), True

    def _analyze(
        self, findings: tuple[FindingDraft, ...], document_type: str | None
    ) -> NeuralResult:
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
            raise AuditModelError("LLM analysis failed") from exc

    def _mark_error(self, document_id: int) -> None:
        with self._session_factory.begin() as session:
            document = session.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.ERROR.value


def _document_context(document: Document) -> DocumentContext:
    candidates = json.loads(document.classification_candidates or "[]")
    return DocumentContext(
        classification_status=document.classification_status or "unknown",
        confirmed_document_types=tuple(item.code for item in document.confirmed_types),
        candidate_document_types=tuple(item["code"] for item in candidates),
        confidence=document.classification_confidence or 0.0,
    )


def _applied_legal_acts(
    session: Session, resolution: ResolutionResult
) -> list[dict[str, object]]:
    ids = {
        rule.legal_act_id
        for rule in resolution.selected_rules
        if rule.legal_act_id is not None
    }
    acts = session.scalars(
        select(LegalAct).where(LegalAct.id.in_(ids)).order_by(LegalAct.id)
    ).all()
    return [{"id": act.id, "code": act.code, "title": act.title} for act in acts]


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
        applicability_scope=rule.applicability_scope,
        document_types=tuple(item.code for item in rule.document_types),
        parameters=parameters,
        legal_act_id=rule.legal_act_id,
        is_active=rule.is_active,
    )


def _finding_key(finding: FindingDraft) -> str:
    start = "" if finding.start_char is None else finding.start_char
    end = "" if finding.end_char is None else finding.end_char
    return f"{finding.rule_code}:{start}:{end}"
