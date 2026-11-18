"""Persistence adapter for audit results."""

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
import logging
import sqlite3

from sqlalchemy import delete, select
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
    DocumentStatement,
    LegalAct,
)
from edm_auditor.model_config import detect_source_language
from edm_auditor.rag.exceptions import RAGError

from .engine import AuditEngine
from .llm_interpreter import LLMInterpreter
from .matching import MATCH_PROMPT_VERSION, RuleMatcher
from .models import AuditResult, FindingDraft, RuleSpec, StatementSpec
from .neural_errors import AuditModelError, DocumentTooLargeForAudit
from .neural_models import NeuralAnalysis, NeuralFinding, NeuralResult


logger = logging.getLogger(__name__)

# These checks compare every value of a kind, so the model confirms what each value means.
SURROUNDING_CHARS = 200


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
        statement_prompt_version: str = "1",
        rule_matcher: RuleMatcher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine
        self._neural_interpreter = neural_interpreter
        self._rag_recommender = rag_recommender
        self._statement_prompt_version = statement_prompt_version
        self._matcher = rule_matcher
        self._resolver = RuleApplicabilityResolver()

    def preview(
        self, document_id: int, selection: SelectionConfig | None = None
    ) -> ResolutionResult:
        """Resolve the same rule set that an audit with this selection would use."""
        with self._session_factory() as session:
            return self._resolve(session, self._load(session, document_id), selection)

    def extract_document_statements(
        self, document_id: int, *, force: bool = False
    ) -> tuple[StatementSpec, ...]:
        """Extract document statements once per prompt version and persist them on the document."""
        with self._session_factory() as session:
            document = self._load(session, document_id)
            if (
                not force
                and document.statements_version == self._statement_prompt_version
            ):
                return tuple(_to_statement_spec(item) for item in document.statements)
            text = document.raw_text

        extracted = self._engine.extract_statements(text)
        with self._session_factory.begin() as session:
            document = self._load(session, document_id)
            session.execute(
                delete(DocumentStatement).where(
                    DocumentStatement.document_id == document_id
                )
            )
            document.statements_version = self._statement_prompt_version
            rows = [
                DocumentStatement(
                    document_id=document_id,
                    subject=item.subject,
                    statement_text=item.statement_text,
                    constraint_json=(
                        json.dumps(item.constraint_json, ensure_ascii=False, sort_keys=True)
                        if item.constraint_json is not None
                        else None
                    ),
                    source_quote=item.source_quote,
                    start_char=item.start_char,
                    end_char=item.end_char,
                    prompt_version=self._statement_prompt_version,
                )
                for item in extracted
            ]
            session.add_all(rows)
            session.flush()
            return tuple(_to_statement_spec(row) for row in rows)

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
                text = document.raw_text
                document_type = (
                    ", ".join(item.code for item in document.confirmed_types) or None
                )
                context = _document_context(document)
                applied_acts = _applied_legal_acts(session, resolution)
                cached_statements: tuple[StatementSpec, ...] | None = (
                    tuple(_to_statement_spec(item) for item in document.statements)
                    if document.statements_version == self._statement_prompt_version
                    else None
                )

            # SQLite allows one writer, so no transaction stays open during model calls.
            if cached_statements is None:
                extracted_statements = self._engine.extract_statements(text)
                with self._session_factory.begin() as session:
                    document = self._load(session, document_id)
                    session.execute(
                        delete(DocumentStatement).where(
                            DocumentStatement.document_id == document_id
                        )
                    )
                    document.statements_version = self._statement_prompt_version
                    rows = [
                        DocumentStatement(
                            document_id=document_id,
                            subject=item.subject,
                            statement_text=item.statement_text,
                            constraint_json=(
                                json.dumps(
                                    item.constraint_json,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                )
                                if item.constraint_json is not None
                                else None
                            ),
                            source_quote=item.source_quote,
                            start_char=item.start_char,
                            end_char=item.end_char,
                            prompt_version=self._statement_prompt_version,
                        )
                        for item in extracted_statements
                    ]
                    session.add_all(rows)
                    session.flush()
                    cached_statements = tuple(_to_statement_spec(row) for row in rows)

            if self._matcher is not None:
                candidates, neural, rejected, matching = self._match(
                    resolution.selected_rules, cached_statements, text, document_type
                )
                result = candidates
            else:
                candidates = self._engine.audit(
                    text, resolution.selected_rules, statements=cached_statements
                )
                neural = self._analyze(candidates.findings, document_type, text)
                result, neural, rejected = _apply_model_verdicts(candidates, neural)
                matching = None
            neural = _with_legal_basis(neural, result.findings, applied_acts)
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
                "rejected_candidates": rejected,
                "matching": matching,
                "selection": selection_snapshot(
                    selection or SelectionConfig(), context, resolution, applied_acts
                ),
            }

            with self._session_factory.begin() as session:
                document = self._load(session, document_id)
                # A rule or an act could be deleted while the models were running.
                rule_ids = set(session.scalars(select(AuditRule.id)).all())
                acts = {act["id"]: act for act in applied_acts}
                legal_act_ids = set(session.scalars(select(LegalAct.id)).all())
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
                        rule_id=finding.rule_id if finding.rule_id in rule_ids else None,
                        legal_act_id=(
                            finding.legal_act_id
                            if finding.legal_act_id in legal_act_ids
                            else None
                        ),
                        severity=finding.severity,
                        description=finding.description,
                        start_char=finding.start_char,
                        end_char=finding.end_char,
                        quote=finding.quote,
                        recommendation=finding.recommendation,
                        finding_key=_finding_key(finding),
                        rule_code=finding.rule_code,
                        rule_name=finding.rule_name or None,
                        legal_act_code=acts.get(finding.legal_act_id, {}).get("code"),
                        legal_act_title=acts.get(finding.legal_act_id, {}).get("title"),
                        norm_quote=finding.norm_quote,
                        statement_text=finding.statement_text,
                        evaluation_mode=finding.evaluation_mode,
                    )
                    for finding in result.findings
                ]
                session.add(report)
                document.status = DocumentStatus.AUDITED.value
                session.flush()
                return report
        except (
            LookupError,
            ValueError,
            TypeError,
            AuditModelError,
            DocumentTooLargeForAudit,
            SQLAlchemyError,
        ):
            self._mark_error(document_id)
            raise

    def _load(self, session: Session, document_id: int) -> Document:
        document = session.scalar(
            select(Document)
            .options(
                selectinload(Document.paragraphs),
                selectinload(Document.statements),
            )
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

    def _match(
        self,
        rules: Sequence[RuleSpec],
        statements: Sequence[StatementSpec],
        text: str,
        document_type: str | None,
    ) -> tuple[AuditResult, NeuralResult, list[dict[str, object]], dict[str, object]]:
        """Compare the rules with the document statements; the verdicts double as explanations."""
        try:
            outcome = self._matcher.match(
                rules,
                statements,
                text,
                document_type=document_type,
                output_language=detect_source_language(text),
            )
        except AuditModelError:
            raise
        except (RuntimeError, ValueError, TypeError) as exc:
            raise AuditModelError("LLM matching failed") from exc
        findings = tuple(item.finding for item in outcome.findings)
        neural = NeuralResult(
            status="completed",
            model=outcome.model,
            prompt_version=MATCH_PROMPT_VERSION,
            analyses=tuple(
                NeuralAnalysis(
                    finding_key=_finding_key(item.finding),
                    explanation=item.explanation,
                    recommendation=item.recommendation,
                    confidence=item.confidence,
                )
                for item in outcome.findings
            ),
            general_summary=outcome.general_summary,
        )
        matching = {
            "pairs": list(outcome.pairs),
            "unchecked_rules": list(outcome.unchecked),
            "inapplicable_rules": list(outcome.inapplicable),
            "requests": outcome.requests,
        }
        return AuditResult(findings), neural, [], matching

    def _analyze(
        self,
        findings: tuple[FindingDraft, ...],
        document_type: str | None,
        text: str,
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
                norm_quote=finding.norm_quote,
                surrounding_text=_surrounding_text(text, finding),
                requires_confirmation=finding.requires_confirmation,
            )
            for finding in findings
        )
        try:
            return self._neural_interpreter.analyze(
                neural_findings,
                document_type=document_type,
                output_language=detect_source_language(text),
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


def _surrounding_text(text: str, finding: FindingDraft) -> str | None:
    """Show the model what the value refers to; a window survives wrapped lines."""
    if finding.start_char is None or finding.end_char is None:
        return None
    start = max(finding.start_char - SURROUNDING_CHARS, 0)
    return text[start : finding.end_char + SURROUNDING_CHARS].strip()


def _apply_model_verdicts(
    candidates: AuditResult, neural: NeuralResult
) -> tuple[AuditResult, NeuralResult, list[dict[str, object]]]:
    """Report only confirmed findings and keep the rejected ones for inspection."""
    verdicts = {item.finding_key: item for item in neural.analyses}
    findings: list[FindingDraft] = []
    rejected: list[dict[str, object]] = []
    for finding in candidates.findings:
        verdict = verdicts.get(_finding_key(finding))
        if verdict is None or verdict.is_violation:
            findings.append(finding)
            continue
        rejected.append(
            {
                "rule_code": finding.rule_code,
                "start_char": finding.start_char,
                "end_char": finding.end_char,
                "quote": finding.quote,
                "reason": verdict.explanation,
            }
        )
    return (
        replace(candidates, findings=tuple(findings)),
        replace(
            neural,
            analyses=tuple(item for item in neural.analyses if item.is_violation),
        ),
        rejected,
    )


def _with_legal_basis(
    neural: NeuralResult,
    findings: Sequence[FindingDraft],
    legal_acts: Sequence[dict[str, object]],
) -> NeuralResult:
    """Cite the norm from the rule itself: a model could invent a reference."""
    acts = {act["id"]: act for act in legal_acts}
    by_key = {_finding_key(finding): finding for finding in findings}

    def basis(key: str) -> tuple[dict[str, object], ...]:
        finding = by_key.get(key)
        act = acts.get(finding.legal_act_id) if finding is not None else None
        if act is None:
            return ()
        return (
            {
                "legal_act_id": act["id"],
                "code": act["code"],
                "title": act["title"],
                "quote": finding.norm_quote,
            },
        )

    return replace(
        neural,
        analyses=tuple(
            replace(item, legal_basis=basis(item.finding_key)) for item in neural.analyses
        ),
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
    constraint_json = json.loads(rule.constraint_json) if rule.constraint_json else None
    if constraint_json is not None and not isinstance(constraint_json, dict):
        raise ValueError(f"rule {rule.rule_code} constraint_json must be an object")
    return RuleSpec(
        rule_id=rule.id,
        rule_code=rule.rule_code,
        subject=rule.subject,
        constraint_text=rule.constraint_text,
        severity=rule.severity,
        condition=rule.condition,
        constraint_json=constraint_json,
        applicability_scope=rule.applicability_scope,
        document_types=tuple(item.code for item in rule.document_types),
        legal_act_id=rule.legal_act_id,
        is_active=rule.is_active,
        source_quote=rule.source_quote,
    )


def _to_statement_spec(statement: DocumentStatement) -> StatementSpec:
    constraint_json = (
        json.loads(statement.constraint_json) if statement.constraint_json else None
    )
    return StatementSpec(
        statement_id=statement.id,
        subject=statement.subject,
        statement_text=statement.statement_text,
        source_quote=statement.source_quote,
        start_char=statement.start_char,
        end_char=statement.end_char,
        constraint_json=constraint_json,
        prompt_version=statement.prompt_version,
    )


def _finding_key(finding: FindingDraft) -> str:
    start = "" if finding.start_char is None else finding.start_char
    end = "" if finding.end_char is None else finding.end_char
    return f"{finding.rule_code}:{start}:{end}"
