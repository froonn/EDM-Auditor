"""Determine and store the applicability of rules generated from a legal act."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from edm_auditor.classification.models import ClassificationStatus
from edm_auditor.classification.store import classify_text
from edm_auditor.database.models import AuditRule, DocumentType, LegalAct

from .models import ApplicabilityScope

SOURCE_LEGAL_ACT = "legal_act"
SOURCE_LEGAL_ACT_CLASSIFIER = "legal_act_classifier"
SOURCE_MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class RuleApplicability:
    scope: ApplicabilityScope
    document_types: tuple[DocumentType, ...]
    confidence: float | None
    source: str


def legal_act_applicability(session: Session, legal_act: LegalAct) -> RuleApplicability:
    """Explicit act types win; otherwise classify the act but never assume universal."""
    if legal_act.document_types:
        return RuleApplicability(
            ApplicabilityScope.TYPED,
            tuple(legal_act.document_types),
            1.0,
            SOURCE_LEGAL_ACT,
        )
    result = classify_text(session, legal_act.article_text, title=legal_act.title)
    if result.status is not ClassificationStatus.CLASSIFIED:
        return RuleApplicability(
            ApplicabilityScope.UNKNOWN,
            (),
            result.confidence,
            SOURCE_LEGAL_ACT_CLASSIFIER,
        )
    return RuleApplicability(
        ApplicabilityScope.TYPED,
        tuple(
            session.get(DocumentType, code) for code in result.confirmed_document_types
        ),
        result.confidence,
        SOURCE_LEGAL_ACT_CLASSIFIER,
    )


def apply_rule_applicability(rule: AuditRule, applicability: RuleApplicability) -> None:
    rule.applicability_scope = applicability.scope.value
    rule.document_types = list(applicability.document_types)
    rule.applicability_confidence = applicability.confidence
    rule.applicability_source = applicability.source
