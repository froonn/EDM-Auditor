"""Contracts for rule applicability and audit rule selection."""

from dataclasses import dataclass, field
from enum import StrEnum


class ApplicabilityScope(StrEnum):
    UNIVERSAL = "universal"
    TYPED = "typed"
    MANUAL_ONLY = "manual_only"
    UNKNOWN = "unknown"


class SelectionMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    COMBINED = "combined"
    ALL = "all"


class ResolutionStatus(StrEnum):
    READY = "ready"
    NEEDS_CONFIGURATION = "needs_configuration"
    NO_APPLICABLE_RULES = "no_applicable_rules"


class SelectionReason(StrEnum):
    RULE_INCLUDED_BY_USER = "rule_included_by_user"
    RULE_SELECTED_BY_LEGAL_ACT = "rule_selected_by_legal_act"
    RULE_SELECTED_BY_ALL_MODE = "rule_selected_by_all_mode"
    RULE_UNIVERSAL = "rule_universal"
    RULE_MATCHED_DOCUMENT_TYPE = "rule_matched_document_type"
    RULE_EXCLUDED_BY_USER = "rule_excluded_by_user"
    RULE_EXCLUDED_BY_DOCUMENT_TYPE = "rule_excluded_by_document_type"
    RULE_EXCLUDED_BY_LEGAL_ACT_SCOPE = "rule_excluded_by_legal_act_scope"
    RULE_MANUAL_ONLY = "rule_manual_only"
    RULE_APPLICABILITY_UNKNOWN = "rule_applicability_unknown"
    RULE_INACTIVE = "rule_inactive"
    MANUAL_SELECTION_REQUIRED = "manual_selection_required"


class SelectionWarning(StrEnum):
    DOCUMENT_TYPE_UNKNOWN = "document_type_unknown"
    CLASSIFICATION_LOW_CONFIDENCE = "classification_low_confidence"
    MANUAL_SELECTION_REQUIRED = "manual_selection_required"
    NO_APPLICABLE_RULES = "no_applicable_rules"
    RULES_WITH_UNKNOWN_APPLICABILITY = "rules_with_unknown_applicability"
    ALL_MODE_FALSE_POSITIVE_RISK = "all_mode_false_positive_risk"
    RAG_CANDIDATE_BELOW_THRESHOLD = "rag_candidate_below_threshold"
    RAG_UNAVAILABLE = "rag_unavailable"


class InvalidSelection(ValueError):
    """The requested selection contradicts the resolver contract."""


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """User request; the ``all`` mode exists only behind an explicit confirmation."""

    mode: SelectionMode = SelectionMode.AUTOMATIC
    legal_act_ids: frozenset[int] = frozenset()
    included_rule_ids: frozenset[int] = frozenset()
    excluded_rule_ids: frozenset[int] = frozenset()
    confirm_all: bool = False

    def __post_init__(self) -> None:
        if self.mode is SelectionMode.ALL and not self.confirm_all:
            raise InvalidSelection("the all mode requires an explicit confirmation")


@dataclass(frozen=True, slots=True)
class DocumentContext:
    """Classification facts; candidates are advisory and never enable a typed rule."""

    classification_status: str = "unknown"
    confirmed_document_types: tuple[str, ...] = ()
    candidate_document_types: tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class RagCandidate:
    """A retrieved fragment; it can inform the user but never selects a rule."""

    legal_act_id: int
    rule_id: int | None
    score: float
    threshold: float


@dataclass(frozen=True, slots=True)
class RagRecommendation:
    legal_act_id: int
    rule_id: int | None
    score: float
    threshold: float
    reason: str


@dataclass(frozen=True, slots=True)
class RuleDecision:
    rule_id: int
    rule_code: str
    name: str
    legal_act_id: int | None
    applicability_scope: str
    document_types: tuple[str, ...]
    selected: bool
    reason: SelectionReason


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    status: ResolutionStatus
    selected_rules: tuple = ()
    decisions: tuple[RuleDecision, ...] = ()
    warnings: tuple[SelectionWarning, ...] = ()
    recommendations: tuple[RagRecommendation, ...] = field(default=())

    @property
    def selected_rule_ids(self) -> tuple[int, ...]:
        return tuple(rule.rule_id for rule in self.selected_rules)
