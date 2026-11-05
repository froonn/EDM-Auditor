import pytest

from edm_auditor.applicability import (
    ApplicabilityScope,
    DocumentContext,
    InvalidSelection,
    RagCandidate,
    ResolutionStatus,
    RuleApplicabilityResolver,
    SelectionConfig,
    SelectionMode,
    SelectionReason,
    SelectionWarning,
)
from edm_auditor.audit_engine.models import RuleSpec

TRIP = DocumentContext("classified", ("business_trip_order",), ("business_trip_order",), 0.9)
UNKNOWN = DocumentContext()
REVIEW = DocumentContext("needs_review", (), ("payroll_order",), 0.3)


def rule(rule_id, scope="unknown", types=(), act=None, active=True) -> RuleSpec:
    return RuleSpec(
        rule_id=rule_id,
        rule_code=f"rule-{rule_id}",
        name=f"Rule {rule_id}",
        severity="high",
        check_type="keyword",
        applicability_scope=scope,
        document_types=types,
        legal_act_id=act,
        is_active=active,
    )


def resolve(rules, document=TRIP, config=None, **kwargs):
    return RuleApplicabilityResolver().resolve(rules, document, config, **kwargs)


def reason(result, rule_id):
    return next(item.reason for item in result.decisions if item.rule_id == rule_id)


def test_typed_rule_is_selected_only_for_a_matching_confirmed_type() -> None:
    result = resolve(
        [
            rule(1, "typed", ("business_trip_order",)),
            rule(2, "typed", ("payroll_order",)),
        ]
    )

    assert result.status is ResolutionStatus.READY
    assert result.selected_rule_ids == (1,)
    assert reason(result, 1) is SelectionReason.RULE_MATCHED_DOCUMENT_TYPE
    assert reason(result, 2) is SelectionReason.RULE_EXCLUDED_BY_DOCUMENT_TYPE


@pytest.mark.parametrize("code", ["business_trip_order", "travel_expense_report"])
def test_rule_with_several_types_matches_any_of_them(code) -> None:
    document = DocumentContext("classified", (code,))

    result = resolve(
        [rule(1, "typed", ("business_trip_order", "travel_expense_report"))], document
    )

    assert result.selected_rule_ids == (1,)


def test_document_with_several_types_matches_by_or() -> None:
    document = DocumentContext("classified", ("business_trip_order", "payroll_order"))

    result = resolve(
        [
            rule(1, "typed", ("business_trip_order",)),
            rule(2, "typed", ("payroll_order",)),
            rule(3, "typed", ("vacation_order",)),
        ],
        document,
    )

    assert result.selected_rule_ids == (1, 2)


def test_universal_rule_applies_to_any_classified_document() -> None:
    for code in ("business_trip_order", "payroll_order"):
        result = resolve([rule(1, "universal")], DocumentContext("classified", (code,)))

        assert result.selected_rule_ids == (1,)
        assert reason(result, 1) is SelectionReason.RULE_UNIVERSAL


def test_unknown_and_manual_only_scopes_are_not_selected_automatically() -> None:
    result = resolve(
        [rule(1, "universal"), rule(2, "unknown"), rule(3, "manual_only")]
    )

    assert result.selected_rule_ids == (1,)
    assert reason(result, 2) is SelectionReason.RULE_APPLICABILITY_UNKNOWN
    assert reason(result, 3) is SelectionReason.RULE_MANUAL_ONLY
    assert SelectionWarning.RULES_WITH_UNKNOWN_APPLICABILITY in result.warnings


def test_inactive_rule_is_never_selected_even_when_included() -> None:
    result = resolve(
        [rule(1, "universal", active=False), rule(2, "universal")],
        config=SelectionConfig(included_rule_ids=frozenset({1})),
    )

    assert result.selected_rule_ids == (2,)
    assert reason(result, 1) is SelectionReason.RULE_INACTIVE


@pytest.mark.parametrize("document, warning", [
    (UNKNOWN, SelectionWarning.DOCUMENT_TYPE_UNKNOWN),
    (REVIEW, SelectionWarning.CLASSIFICATION_LOW_CONFIDENCE),
])
def test_unconfirmed_type_requires_configuration_instead_of_running_rules(
    document, warning
) -> None:
    result = resolve(
        [rule(1, "universal"), rule(2, "typed", ("payroll_order",))], document
    )

    assert result.status is ResolutionStatus.NEEDS_CONFIGURATION
    assert result.selected_rules == ()
    assert not any(item.selected for item in result.decisions)
    assert warning in result.warnings
    assert SelectionWarning.MANUAL_SELECTION_REQUIRED in result.warnings


def test_candidate_type_never_enables_a_typed_rule() -> None:
    result = resolve(
        [rule(1, "typed", ("payroll_order",))],
        REVIEW,
        SelectionConfig(mode=SelectionMode.COMBINED, included_rule_ids=frozenset({99})),
    )

    assert reason(result, 1) is SelectionReason.RULE_EXCLUDED_BY_DOCUMENT_TYPE


def test_exclusion_beats_inclusion_and_automatic_match() -> None:
    result = resolve(
        [rule(1, "universal"), rule(2, "universal")],
        config=SelectionConfig(
            included_rule_ids=frozenset({1}), excluded_rule_ids=frozenset({1})
        ),
    )

    assert result.selected_rule_ids == (2,)
    assert reason(result, 1) is SelectionReason.RULE_EXCLUDED_BY_USER


def test_inclusion_overrides_every_scope() -> None:
    result = resolve(
        [
            rule(1, "manual_only"),
            rule(2, "unknown"),
            rule(3, "typed", ("payroll_order",)),
        ],
        config=SelectionConfig(included_rule_ids=frozenset({1, 2, 3})),
    )

    assert result.selected_rule_ids == (1, 2, 3)
    assert {item.reason for item in result.decisions} == {
        SelectionReason.RULE_INCLUDED_BY_USER
    }


def test_automatic_mode_restricts_rules_to_selected_legal_acts() -> None:
    result = resolve(
        [
            rule(1, "typed", ("business_trip_order",), act=1),
            rule(2, "typed", ("business_trip_order",), act=2),
            rule(3, "universal"),
        ],
        config=SelectionConfig(legal_act_ids=frozenset({1})),
    )

    assert result.selected_rule_ids == (1, 3)
    assert reason(result, 2) is SelectionReason.RULE_EXCLUDED_BY_LEGAL_ACT_SCOPE


def test_manual_mode_uses_only_the_explicit_selection() -> None:
    result = resolve(
        [
            rule(1, "typed", ("payroll_order",), act=1),
            rule(2, "unknown", act=1),
            rule(3, "manual_only", act=1),
            rule(4, "universal", act=2),
            rule(5, "universal"),
        ],
        UNKNOWN,
        SelectionConfig(
            mode=SelectionMode.MANUAL,
            legal_act_ids=frozenset({1}),
            included_rule_ids=frozenset({5}),
        ),
    )

    assert result.status is ResolutionStatus.READY
    assert result.selected_rule_ids == (1, 2, 5)
    assert reason(result, 3) is SelectionReason.RULE_MANUAL_ONLY
    assert reason(result, 4) is SelectionReason.MANUAL_SELECTION_REQUIRED


def test_manual_mode_without_a_selection_requires_configuration() -> None:
    result = resolve([rule(1, "universal")], config=SelectionConfig(mode=SelectionMode.MANUAL))

    assert result.status is ResolutionStatus.NEEDS_CONFIGURATION
    assert SelectionWarning.MANUAL_SELECTION_REQUIRED in result.warnings


def test_combined_mode_adds_explicit_selection_to_automatic_rules() -> None:
    result = resolve(
        [
            rule(1, "typed", ("business_trip_order",), act=1),
            rule(2, "typed", ("payroll_order",), act=2),
            rule(3, "typed", ("vacation_order",), act=3),
        ],
        config=SelectionConfig(mode=SelectionMode.COMBINED, legal_act_ids=frozenset({2})),
    )

    assert result.selected_rule_ids == (1, 2)
    assert reason(result, 2) is SelectionReason.RULE_SELECTED_BY_LEGAL_ACT
    assert reason(result, 3) is SelectionReason.RULE_EXCLUDED_BY_DOCUMENT_TYPE


def test_all_mode_requires_confirmation() -> None:
    with pytest.raises(InvalidSelection, match="confirmation"):
        SelectionConfig(mode=SelectionMode.ALL)


def test_all_mode_is_explicit_broad_and_still_honours_exclusions() -> None:
    result = resolve(
        [
            rule(1, "typed", ("payroll_order",)),
            rule(2, "unknown"),
            rule(3, "manual_only"),
            rule(4, "universal", active=False),
        ],
        UNKNOWN,
        SelectionConfig(
            mode=SelectionMode.ALL, confirm_all=True, excluded_rule_ids=frozenset({3})
        ),
    )

    assert result.status is ResolutionStatus.READY
    assert result.selected_rule_ids == (1, 2)
    assert SelectionWarning.ALL_MODE_FALSE_POSITIVE_RISK in result.warnings


def test_no_matching_rules_is_a_diagnosable_result() -> None:
    result = resolve([rule(1, "typed", ("payroll_order",))])

    assert result.status is ResolutionStatus.NO_APPLICABLE_RULES
    assert SelectionWarning.NO_APPLICABLE_RULES in result.warnings
    assert reason(result, 1) is SelectionReason.RULE_EXCLUDED_BY_DOCUMENT_TYPE


def test_duplicate_rules_are_selected_once() -> None:
    result = resolve([rule(1, "universal"), rule(1, "universal")])

    assert result.selected_rule_ids == (1,)
    assert len(result.decisions) == 1


def test_rag_candidate_never_selects_a_rule_from_another_act() -> None:
    result = resolve(
        [rule(1, "typed", ("payroll_order",), act=7), rule(2, "universal")],
        rag_candidates=[RagCandidate(7, 1, score=0.99, threshold=0.5)],
    )

    assert result.selected_rule_ids == (2,)
    assert result.recommendations[0].rule_id == 1
    assert result.recommendations[0].reason == "rag_candidate_above_threshold"


def test_low_rag_score_is_reported_with_score_and_threshold() -> None:
    result = resolve(
        [rule(1, "universal")],
        rag_candidates=[
            RagCandidate(7, None, score=0.1, threshold=0.5),
            RagCandidate(7, None, score=0.2, threshold=0.5),
        ],
    )

    assert SelectionWarning.RAG_CANDIDATE_BELOW_THRESHOLD in result.warnings
    assert len(result.recommendations) == 1
    assert result.recommendations[0].score == 0.2
    assert result.recommendations[0].threshold == 0.5


def test_scope_values_match_the_contract() -> None:
    assert {item.value for item in ApplicabilityScope} == {
        "universal",
        "typed",
        "manual_only",
        "unknown",
    }
