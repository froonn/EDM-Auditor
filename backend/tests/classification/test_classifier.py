from pathlib import Path

import pytest

from edm_auditor.classification import (
    ClassificationStatus,
    DocumentTypeProfile,
    classify_document,
)
from edm_auditor.classification.catalog import DEFAULT_DOCUMENT_TYPES

EXAMPLES = Path(__file__).parents[2] / "examples"
PROFILES = [item.profile for item in DEFAULT_DOCUMENT_TYPES]


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("business_trip_order.txt", "business_trip_order"),
        ("compliant_business_trip_order.txt", "business_trip_order"),
        ("remote_work_agreement.txt", "remote_work_agreement"),
        ("compliant_remote_work_agreement.txt", "remote_work_agreement"),
        ("payroll_order.txt", "payroll_order"),
        ("compliant_payroll_order.txt", "payroll_order"),
        ("legal_act_business_trip.txt", "business_trip_order"),
        ("legal_act_remote_work.txt", "remote_work_agreement"),
        ("legal_act_payments.txt", "payroll_order"),
    ],
)
def test_examples_are_classified_from_content_alone(filename, expected) -> None:
    text = (EXAMPLES / filename).read_text(encoding="utf-8")

    result = classify_document(text, PROFILES)

    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.confirmed_document_types == (expected,)
    assert result.confidence >= 0.6


def test_employment_contract_fixture_is_classified() -> None:
    text = (Path(__file__).parents[1] / "fixtures" / "employment_contract.txt").read_text(
        encoding="utf-8"
    )

    result = classify_document(text, PROFILES)

    assert result.confirmed_document_types == ("employment_contract",)


def test_unrelated_text_is_unknown_and_has_no_types() -> None:
    result = classify_document("Employee receives 14 days leave.", PROFILES)

    assert result.status is ClassificationStatus.UNKNOWN
    assert result.confirmed_document_types == ()
    assert result.candidate_types == ()


def test_weak_signal_needs_review_without_confirming_a_type() -> None:
    text = "Служебная записка.\nСогласовать отчет о командировке и служебные расходы."

    result = classify_document(text, PROFILES)

    assert result.status is ClassificationStatus.NEEDS_REVIEW
    assert result.confirmed_document_types == ()
    assert [item.code for item in result.candidate_types] == ["business_trip_order"]


def test_file_name_alone_only_suggests_a_candidate() -> None:
    result = classify_document("Текст без признаков.", PROFILES, filename="payroll_order.txt")

    assert result.status is ClassificationStatus.NEEDS_REVIEW
    assert result.confirmed_document_types == ()


def test_document_can_have_several_confirmed_types() -> None:
    profiles = [
        DocumentTypeProfile("first", title_terms=("приказ",), body_terms=("командировк", "отчет")),
        DocumentTypeProfile("second", title_terms=("расход",), body_terms=("командировк", "отчет")),
    ]

    result = classify_document("Приказ и отчет о расходах\nКомандировка, отчет.", profiles)

    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.confirmed_document_types == ("first", "second")


def test_close_competitor_without_heading_requires_review() -> None:
    profiles = [
        DocumentTypeProfile("headed", title_terms=("приказ",), body_terms=("аванс",)),
        DocumentTypeProfile(
            "competitor",
            title_terms=("заработ",),
            body_terms=("аванс", "оклад"),
            structure_terms=("приказ",),
        ),
    ]

    result = classify_document(
        "Приказ\nАванс и оклад.", profiles, title="заработная плата"
    )

    assert result.status is ClassificationStatus.NEEDS_REVIEW


def test_entity_signal_contributes_to_the_score() -> None:
    profile = DocumentTypeProfile("typed", body_terms=("аванс",), entity_kinds=("money",))

    with_entity = classify_document(
        "Документ\nАванс.", [profile], entity_kinds={"money"}
    )
    without_entity = classify_document("Документ\nАванс.", [profile])

    assert with_entity.confidence == 0.25
    assert without_entity.candidate_types == ()
