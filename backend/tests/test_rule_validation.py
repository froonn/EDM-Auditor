import pytest

from edm_auditor.rule_validation import (
    RuleValidationError,
    validate_generated_rule,
    validate_manual_constraint,
)


def _rule(**overrides):
    value = {
        "subject": "Минимальная продолжительность отпуска",
        "constraint_text": "Отпуск должен быть не менее 24 дней.",
        "constraint_json": {"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
        "condition": "",
        "severity": "high",
        "source_quote": "Отпуск должен быть не менее 24 дней.",
    }
    value.update(overrides)
    return value


def test_generated_rule_is_normalized_and_quote_range_is_resolved() -> None:
    result = validate_generated_rule(
        _rule(),
        source_text="Статья 1. Отпуск должен быть не менее 24 дней.",
        source_language="ru",
        source_location="act:chunk-0",
        index=1,
    )

    assert result["source_start"] == 10
    assert result["source_end"] == 10 + len(result["source_quote"])
    assert result["constraint_json"] == {
        "kind": "value",
        "operator": "gte",
        "value": 24,
        "unit": "day",
    }


def test_quote_matching_allows_normalized_whitespace_and_preserves_source_range() -> None:
    source = "Работодатель обязан предоставить\n\nработнику письменное уведомление."
    result = validate_generated_rule(
        _rule(
            constraint_text="Работодатель обязан предоставить работнику письменное уведомление.",
            constraint_json=None,
            source_quote="Работодатель обязан предоставить работнику письменное уведомление.",
        ),
        source_text=source,
        source_language="ru",
        source_location="act:chunk-0",
        index=1,
    )

    assert result["source_quote"] == source
    assert result["source_start"] == 0
    assert result["source_end"] == len(source)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("source_quote", "missing text", "quote_not_found"),
        ("subject", "", "invalid_schema"),
        ("subject", "Minimum leave", "language_mismatch"),
    ],
)
def test_generated_rule_rejection_has_explicit_category(field, value, expected) -> None:
    with pytest.raises(RuleValidationError) as error:
        validate_generated_rule(
            _rule(**{field: value}),
            source_text="Отпуск должен быть не менее 24 дней.",
            source_language="ru",
            source_location="act:chunk-0",
            index=1,
        )

    assert error.value.code == expected


def test_duplicate_quote_is_rejected_as_ambiguous() -> None:
    with pytest.raises(RuleValidationError, match="ambiguous"):
        validate_generated_rule(
            _rule(),
            source_text=(
                "Отпуск должен быть не менее 24 дней. "
                "Отпуск должен быть не менее 24 дней."
            ),
            source_language="ru",
            source_location="act:chunk-0",
            index=1,
        )


@pytest.mark.parametrize(
    "bad_constraint",
    [
        {"kind": "unknown", "operator": "gte", "value": 24, "unit": "day"},
        {"kind": "value", "operator": "gte", "value": "24", "unit": "day"},
        {"kind": "value", "operator": "gte", "value": 24, "unit": "weeks"},
        # Contradicts text number (text says 24, structure says 30).
        {"kind": "value", "operator": "gte", "value": 30, "unit": "day"},
        # Contradicts text operator ("не менее" requires gte/gt, not lte).
        {"kind": "value", "operator": "lte", "value": 24, "unit": "day"},
        {"kind": "frequency", "operator": "gte", "count": 0, "period": "month"},
        {"kind": "day_of_month", "operator": "lte", "day": 32, "month_offset": 1},
    ],
)
def test_bad_or_contradictory_generated_structure_is_dropped_without_rejecting_rule(
    bad_constraint: dict,
) -> None:
    result = validate_generated_rule(
        _rule(constraint_json=bad_constraint),
        source_text="Отпуск должен быть не менее 24 дней.",
        source_language="ru",
        source_location="act:chunk-0",
        index=1,
    )

    assert result["constraint_json"] is None
    assert result["constraint_text"] == "Отпуск должен быть не менее 24 дней."


@pytest.mark.parametrize(
    ("quote", "text", "constraint_json", "expected"),
    [
        (
            "Отпуск должен быть не менее 24 дней.",
            "Отпуск должен быть не менее 24 дней.",
            {"kind": "value", "operator": "gte", "value": 24, "unit": "day", "count": None},
            {"kind": "value", "operator": "gte", "value": 24, "unit": "day"},
        ),
        (
            "Заработная плата выплачивается не реже двух раз в месяц.",
            "Заработная плата выплачивается не реже двух раз в месяц.",
            {"kind": "frequency", "operator": "gte", "count": 2, "period": "month"},
            {"kind": "frequency", "operator": "gte", "count": 2, "period": "month"},
        ),
        (
            "Окончательный расчет производится не позднее 5 числа следующего месяца.",
            "Окончательный расчет производится не позднее 5 числа следующего месяца.",
            {"kind": "day_of_month", "operator": "lte", "day": 5, "month_offset": 1},
            {"kind": "day_of_month", "operator": "lte", "day": 5, "month_offset": 1},
        ),
    ],
)
def test_validator_accepts_supported_constraint_structures(
    quote: str, text: str, constraint_json: dict, expected: dict
) -> None:
    result = validate_generated_rule(
        _rule(constraint_text=text, source_quote=quote, constraint_json=constraint_json),
        source_text=quote,
        source_language="ru",
        source_location="act:chunk-0",
        index=1,
    )

    assert result["constraint_json"] == expected


@pytest.mark.parametrize(
    "invalid_manual",
    [
        {"kind": "regex", "pattern": "("},
        {"kind": "value", "operator": "gte", "value": -1, "unit": "day"},
        {"kind": "frequency", "operator": "gte", "count": 2, "period": "week"},
        {"kind": "day_of_month", "operator": "lte", "day": 40},
        "not-an-object",
    ],
)
def test_manual_constraint_validation_rejects_invalid_structures(invalid_manual) -> None:
    with pytest.raises(RuleValidationError) as error:
        validate_manual_constraint(invalid_manual)

    assert error.value.code == "invalid_rule_parameters"


@pytest.mark.parametrize("gap", ["...", "…", " ... "])
def test_quote_with_ellipsis_matches_from_first_to_last_part(gap: str) -> None:
    source = (
        "В соглашении указываются:\nа) режим рабочего времени;\n"
        "б) порядок взаимодействия работника и нанимателя."
    )
    result = validate_generated_rule(
        _rule(
            constraint_json=None,
            constraint_text="В соглашении указывается порядок взаимодействия.",
            source_quote=f"В соглашении указываются:{gap}б) порядок взаимодействия работника и нанимателя.",
        ),
        source_text=source,
        source_language="ru",
        source_location="act:chunk-0",
        index=1,
    )

    assert result["source_quote"] == source
    assert (result["source_start"], result["source_end"]) == (0, len(source))
