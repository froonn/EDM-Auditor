import pytest

from edm_auditor.rule_validation import RuleValidationError, validate_generated_rule


def _rule(**overrides):
    value = {
        "rule_code": "leave-duration",
        "name": "Минимальная продолжительность отпуска",
        "description": "Отпуск должен быть не менее 24 дней.",
        "severity": "high",
        "check_type": "duration",
        "parameters": {"min_days": 24},
        "source_quote": "Отпуск должен быть не менее 24 дней.",
        "source_location": "act:chunk-0",
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
    assert result["parameters_json"] == '{"min_days": 24}'


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("source_quote", "quote_not_found"),
        ("source_location", "invalid_schema"),
        ("name", "language_mismatch"),
    ],
)
def test_generated_rule_rejection_has_explicit_category(field, expected) -> None:
    value = "missing text" if field == "source_quote" else "act:other"
    if field == "name":
        value = "Minimum leave"
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
    ("check_type", "parameters"),
    [
        ("duration", {"min_days": "24"}),
        ("keyword", {"keywords": []}),
        ("regex", {"pattern": "["}),
        ("date", {"before": "tomorrow"}),
        ("semantic", {"query": ""}),
        ("duration", {"field": "days", "operator": "gte", "value": 24}),
    ],
)
def test_validator_enforces_check_type_contract(check_type, parameters) -> None:
    with pytest.raises(RuleValidationError) as error:
        validate_generated_rule(
            _rule(
                check_type=check_type,
                parameters=parameters,
                source_quote="Отпуск должен быть не менее 24 дней.",
            ),
            source_text="Отпуск должен быть не менее 24 дней.",
            source_language="ru",
            source_location="act:chunk-0",
            index=1,
        )

    assert error.value.code == "invalid_parameters"


@pytest.mark.parametrize(
    ("check_type", "parameters"),
    [
        ("duration", {"max_days": 30}),
        ("numeric", {"entity": "money", "min": 100}),
        ("date", {"after": "2026-01-01"}),
        ("keyword", {"keywords": ["отпуск"], "mode": "required"}),
        ("regex", {"pattern": r"\bотпуск\b"}),
        ("semantic", {"query": "срок отпуска", "k": 3, "threshold": 0.7}),
    ],
)
def test_validator_accepts_supported_parameter_contracts(check_type, parameters) -> None:
    result = validate_generated_rule(
        _rule(check_type=check_type, parameters=parameters),
        source_text="Отпуск должен быть не менее 24 дней.",
        source_language="ru",
        source_location="act:chunk-0",
        index=1,
    )

    assert result["check_type"] == check_type
