"""Determine and store the applicability of rules generated from a legal act."""

from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy.orm import Session

from edm_auditor.classification.models import TypeSuggestion
from edm_auditor.database.models import AuditRule, DocumentType, LegalAct

from .models import ApplicabilityScope

SOURCE_LEGAL_ACT = "legal_act"
SOURCE_LLM = "llm"
SOURCE_MANUAL = "manual"
SOURCE_MIGRATION = "migration"

_APPLICABILITY_FIELDS = (
    "applicability_scope",
    "document_types",
    "applicability_confidence",
    "suggested_type_name",
    "suggested_type_reason",
)


@dataclass(frozen=True, slots=True)
class RuleApplicability:
    scope: ApplicabilityScope
    document_types: tuple[DocumentType, ...]
    confidence: float | None
    source: str


@dataclass(frozen=True, slots=True)
class ModelApplicability:
    """What the model answered for one rule, before the confidence threshold."""

    scope: str
    document_types: tuple[str, ...] = ()
    confidence: float | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "scope": self.scope,
                "document_types": list(self.document_types),
                "confidence": self.confidence,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> "ModelApplicability":
        values = json.loads(value)
        return cls(values["scope"], tuple(values["document_types"]), values["confidence"])


def split_generated_rule(
    payload: dict[str, Any], known_codes: set[str]
) -> tuple[dict[str, Any], ModelApplicability, TypeSuggestion | None]:
    """Separate applicability from the rule; a bad answer only makes the scope unknown."""
    rule = {key: value for key, value in payload.items() if key not in _APPLICABILITY_FIELDS}
    scope = payload.get("applicability_scope")
    codes = payload.get("document_types")
    valid_codes = (
        tuple(dict.fromkeys(code for code in codes if code in known_codes))
        if isinstance(codes, list) and all(isinstance(code, str) for code in codes)
        else ()
    )
    confidence = payload.get("applicability_confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        confidence = None
    if scope == ApplicabilityScope.UNIVERSAL.value:
        applicability = ModelApplicability(scope, (), confidence)
    elif scope == ApplicabilityScope.TYPED.value and valid_codes:
        applicability = ModelApplicability(scope, valid_codes, confidence)
    else:
        applicability = ModelApplicability(ApplicabilityScope.UNKNOWN.value, (), confidence)
    return rule, applicability, _suggestion(payload, applicability)


def generated_rule_applicability(
    session: Session,
    legal_act: LegalAct,
    automatic: str | None,
    *,
    min_confidence: float,
) -> RuleApplicability:
    """Explicit act types win; otherwise use a confident answer of the model."""
    if legal_act.document_types:
        return RuleApplicability(
            ApplicabilityScope.TYPED,
            tuple(legal_act.document_types),
            1.0,
            SOURCE_LEGAL_ACT,
        )
    if automatic is None:
        return RuleApplicability(ApplicabilityScope.UNKNOWN, (), None, SOURCE_LLM)
    answer = ModelApplicability.from_json(automatic)
    unknown = RuleApplicability(
        ApplicabilityScope.UNKNOWN, (), answer.confidence, SOURCE_LLM
    )
    if answer.confidence is None or answer.confidence < min_confidence:
        return unknown
    if answer.scope == ApplicabilityScope.UNIVERSAL.value:
        return RuleApplicability(
            ApplicabilityScope.UNIVERSAL, (), answer.confidence, SOURCE_LLM
        )
    rows = tuple(
        row
        for row in (session.get(DocumentType, code) for code in answer.document_types)
        if row is not None and row.is_active
    )
    if answer.scope != ApplicabilityScope.TYPED.value or not rows:
        return unknown
    return RuleApplicability(ApplicabilityScope.TYPED, rows, answer.confidence, SOURCE_LLM)


def apply_rule_applicability(rule: AuditRule, applicability: RuleApplicability) -> None:
    rule.applicability_scope = applicability.scope.value
    rule.document_types = list(applicability.document_types)
    rule.applicability_confidence = applicability.confidence
    rule.applicability_source = applicability.source


def _suggestion(
    payload: dict[str, Any], applicability: ModelApplicability
) -> TypeSuggestion | None:
    name = payload.get("suggested_type_name")
    reason = payload.get("suggested_type_reason")
    if (
        applicability.scope != ApplicabilityScope.UNKNOWN.value
        or not isinstance(name, str)
        or not name.strip()
    ):
        return None
    return TypeSuggestion(name.strip(), reason.strip() if isinstance(reason, str) else "")
