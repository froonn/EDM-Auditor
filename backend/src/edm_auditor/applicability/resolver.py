"""Select the rules that may be passed to the audit engine for one document."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from .models import (
    ApplicabilityScope,
    DocumentContext,
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

if TYPE_CHECKING:
    from edm_auditor.audit_engine.models import RuleSpec

RAG_CANDIDATE_ABOVE_THRESHOLD = "rag_candidate_above_threshold"


class RuleApplicabilityResolver:
    """Apply selection priorities; RAG results are reported but never select a rule."""

    def resolve(
        self,
        rules: Iterable["RuleSpec"],
        document: DocumentContext,
        config: SelectionConfig | None = None,
        *,
        rag_candidates: Sequence[RagCandidate] = (),
    ) -> ResolutionResult:
        config = config or SelectionConfig()
        unique = {rule.rule_id: rule for rule in rules}
        decisions = tuple(
            self._decide(rule, document, config)
            for rule in sorted(unique.values(), key=lambda item: item.rule_id)
        )
        selected = tuple(
            unique[decision.rule_id] for decision in decisions if decision.selected
        )
        recommendations = _recommendations(rag_candidates)
        warnings = _warnings(document, config, decisions, recommendations)

        if _needs_configuration(document, config):
            return ResolutionResult(
                ResolutionStatus.NEEDS_CONFIGURATION,
                decisions=tuple(replace(item, selected=False) for item in decisions),
                warnings=warnings,
                recommendations=recommendations,
            )
        if not selected:
            return ResolutionResult(
                ResolutionStatus.NO_APPLICABLE_RULES,
                decisions=decisions,
                warnings=(*warnings, SelectionWarning.NO_APPLICABLE_RULES),
                recommendations=recommendations,
            )
        return ResolutionResult(
            ResolutionStatus.READY,
            selected_rules=selected,
            decisions=decisions,
            warnings=warnings,
            recommendations=recommendations,
        )

    def _decide(
        self, rule: "RuleSpec", document: DocumentContext, config: SelectionConfig
    ) -> RuleDecision:
        selected, reason = _selection(rule, document, config)
        return RuleDecision(
            rule_id=rule.rule_id,
            rule_code=rule.rule_code,
            name=rule.name,
            legal_act_id=rule.legal_act_id,
            applicability_scope=rule.applicability_scope,
            document_types=tuple(rule.document_types),
            selected=selected,
            reason=reason,
        )


def _selection(
    rule: "RuleSpec", document: DocumentContext, config: SelectionConfig
) -> tuple[bool, SelectionReason]:
    if not rule.is_active:
        return False, SelectionReason.RULE_INACTIVE
    if rule.rule_id in config.excluded_rule_ids:
        return False, SelectionReason.RULE_EXCLUDED_BY_USER
    if rule.rule_id in config.included_rule_ids:
        return True, SelectionReason.RULE_INCLUDED_BY_USER
    if config.mode is SelectionMode.ALL:
        return True, SelectionReason.RULE_SELECTED_BY_ALL_MODE

    scope = rule.applicability_scope
    in_selected_act = rule.legal_act_id in config.legal_act_ids
    if config.mode in (SelectionMode.MANUAL, SelectionMode.COMBINED) and in_selected_act:
        if scope == ApplicabilityScope.MANUAL_ONLY:
            return False, SelectionReason.RULE_MANUAL_ONLY
        return True, SelectionReason.RULE_SELECTED_BY_LEGAL_ACT
    if config.mode is SelectionMode.MANUAL:
        return False, SelectionReason.MANUAL_SELECTION_REQUIRED

    if (
        config.mode is SelectionMode.AUTOMATIC
        and config.legal_act_ids
        and rule.legal_act_id is not None
        and not in_selected_act
    ):
        return False, SelectionReason.RULE_EXCLUDED_BY_LEGAL_ACT_SCOPE
    if scope == ApplicabilityScope.UNIVERSAL:
        return True, SelectionReason.RULE_UNIVERSAL
    if scope == ApplicabilityScope.TYPED:
        if set(rule.document_types) & set(document.confirmed_document_types):
            return True, SelectionReason.RULE_MATCHED_DOCUMENT_TYPE
        return False, SelectionReason.RULE_EXCLUDED_BY_DOCUMENT_TYPE
    if scope == ApplicabilityScope.MANUAL_ONLY:
        return False, SelectionReason.RULE_MANUAL_ONLY
    return False, SelectionReason.RULE_APPLICABILITY_UNKNOWN


def _needs_configuration(document: DocumentContext, config: SelectionConfig) -> bool:
    """An unconfirmed type needs a decision instead of a silent choice of rules."""
    if config.mode is SelectionMode.ALL:
        return False
    explicit = bool(config.included_rule_ids)
    if config.mode is SelectionMode.MANUAL:
        return not (explicit or config.legal_act_ids)
    if config.mode is SelectionMode.COMBINED:
        explicit = explicit or bool(config.legal_act_ids)
    return not explicit and not document.confirmed_document_types


def _warnings(
    document: DocumentContext,
    config: SelectionConfig,
    decisions: Sequence[RuleDecision],
    recommendations: Sequence[RagRecommendation],
) -> tuple[SelectionWarning, ...]:
    warnings: list[SelectionWarning] = []
    if not document.confirmed_document_types:
        warnings.append(
            SelectionWarning.CLASSIFICATION_LOW_CONFIDENCE
            if document.candidate_document_types
            else SelectionWarning.DOCUMENT_TYPE_UNKNOWN
        )
    if _needs_configuration(document, config):
        warnings.append(SelectionWarning.MANUAL_SELECTION_REQUIRED)
    if config.mode is SelectionMode.ALL:
        warnings.append(SelectionWarning.ALL_MODE_FALSE_POSITIVE_RISK)
    if any(
        item.reason is SelectionReason.RULE_APPLICABILITY_UNKNOWN for item in decisions
    ):
        warnings.append(SelectionWarning.RULES_WITH_UNKNOWN_APPLICABILITY)
    if any(
        item.reason == SelectionWarning.RAG_CANDIDATE_BELOW_THRESHOLD.value
        for item in recommendations
    ):
        warnings.append(SelectionWarning.RAG_CANDIDATE_BELOW_THRESHOLD)
    return tuple(warnings)


def _recommendations(
    candidates: Sequence[RagCandidate],
) -> tuple[RagRecommendation, ...]:
    best: dict[tuple[int, int | None], RagCandidate] = {}
    for item in candidates:
        key = (item.legal_act_id, item.rule_id)
        if key not in best or item.score > best[key].score:
            best[key] = item
    return tuple(
        RagRecommendation(
            legal_act_id=item.legal_act_id,
            rule_id=item.rule_id,
            score=item.score,
            threshold=item.threshold,
            reason=(
                RAG_CANDIDATE_ABOVE_THRESHOLD
                if item.score >= item.threshold
                else SelectionWarning.RAG_CANDIDATE_BELOW_THRESHOLD.value
            ),
        )
        for item in sorted(best.values(), key=lambda value: -value.score)
    )
