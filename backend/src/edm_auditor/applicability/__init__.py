"""Decide which audit rules apply to a document."""

from .models import (
    ApplicabilityScope,
    DocumentContext,
    InvalidSelection,
    RagCandidate,
    RagRecommendation,
    ResolutionResult,
    ResolutionStatus,
    RuleDecision,
    SelectionConfig,
    SelectionMode,
    SelectionReason,
    SelectionWarning,
)
from .resolver import RuleApplicabilityResolver

__all__ = [
    "ApplicabilityScope",
    "DocumentContext",
    "InvalidSelection",
    "RagCandidate",
    "RagRecommendation",
    "ResolutionResult",
    "ResolutionStatus",
    "RuleApplicabilityResolver",
    "RuleDecision",
    "SelectionConfig",
    "SelectionMode",
    "SelectionReason",
    "SelectionWarning",
]
