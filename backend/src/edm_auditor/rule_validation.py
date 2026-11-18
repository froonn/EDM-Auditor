"""Validation and normalization for model-generated and manual audit rules."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .model_config import detect_source_language


_FIELDS = {
    "subject",
    "constraint_text",
    "constraint_json",
    "condition",
    "severity",
    "source_quote",
}
_SEVERITIES = {"low", "medium", "high", "critical"}
_LANGUAGE_FIELDS = ("subject", "constraint_text", "condition", "source_quote")

_CONSTRAINT_KINDS = {"value", "frequency", "day_of_month"}
_CONSTRAINT_OPERATORS = {"gte", "lte", "gt", "lt", "eq"}
_VALUE_UNITS = {"day", "hour", "byn", "%"}
_FREQUENCY_PERIODS = {"month", "year"}

_NUMBER_WORDS: tuple[tuple[str, float], ...] = (
    ("двадцать четыре", 24),
    ("двадцати четырех", 24),
    ("двадцати четырёх", 24),
    ("двадцать пять", 25),
    ("двадцати пяти", 25),
    ("двадцать один", 21),
    ("двадцати одного", 21),
    ("четырнадцать", 14),
    ("четырнадцати", 14),
    ("пятнадцать", 15),
    ("пятнадцати", 15),
    ("шестнадцать", 16),
    ("шестнадцати", 16),
    ("восемнадцать", 18),
    ("восемнадцати", 18),
    ("одиннадцать", 11),
    ("одиннадцати", 11),
    ("двенадцать", 12),
    ("двенадцати", 12),
    ("тридцать", 30),
    ("тридцати", 30),
    ("пятьдесят", 50),
    ("пятидесяти", 50),
    ("шестьдесят", 60),
    ("шестидесяти", 60),
    ("двадцать", 20),
    ("двадцати", 20),
    ("сорок", 40),
    ("сорока", 40),
    ("десять", 10),
    ("десяти", 10),
    ("девять", 9),
    ("девяти", 9),
    ("восемь", 8),
    ("восьми", 8),
    ("семь", 7),
    ("семи", 7),
    ("шесть", 6),
    ("шести", 6),
    ("пять", 5),
    ("пяти", 5),
    ("четыре", 4),
    ("четырех", 4),
    ("четырёх", 4),
    ("три", 3),
    ("трех", 3),
    ("трёх", 3),
    ("трое", 3),
    ("трижды", 3),
    ("два", 2),
    ("двух", 2),
    ("двое", 2),
    ("дважды", 2),
    ("полтора", 1.5),
    ("один", 1),
    ("одного", 1),
    ("одной", 1),
    ("одному", 1),
    ("одним", 1),
)

_LOWER_BOUND_MARKERS = (
    "не менее",
    "не меньше",
    "не реже",
    "не ниже",
    "не может быть меньше",
    "не может быть менее",
    "не позднее чем за",
    "минимум",
)
_UPPER_BOUND_MARKERS = (
    "не более",
    "не больше",
    "не свыше",
    "не чаще",
    "не выше",
    "не может превышать",
    "не превышает",
    "не должен превышать",
    "максимум",
    "в течение",
)


@dataclass(frozen=True)
class RuleValidationError(ValueError):
    """A rejected rule or parameter contract with a stable machine-readable category."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_manual_constraint(constraint_json: Any) -> dict[str, object] | None:
    """Validate structured constraint parameters entered manually or via API."""
    return normalize_constraint_json(constraint_json, strict=True)


def normalize_constraint_json(
    constraint_json: Any,
    *,
    constraint_text: str = "",
    source_quote: str = "",
    strict: bool = False,
) -> dict[str, object] | None:
    """Validate and normalize ``constraint_json``.

    When ``strict`` is False (for model-generated rules), an invalid structure or a structure that
    contradicts the text is dropped (returns ``None``) so the rule stays textual instead of being
    rejected.
    """
    if constraint_json is None:
        return None
    if not isinstance(constraint_json, dict):
        if strict:
            raise RuleValidationError(
                "invalid_rule_parameters", "constraint_json must be an object or null"
            )
        return None

    active = {key: value for key, value in constraint_json.items() if value is not None}
    kind = active.get("kind")
    operator = active.get("operator")
    if not isinstance(kind, str) or kind not in _CONSTRAINT_KINDS:
        return _fail_or_drop("unsupported constraint kind", strict)
    if not isinstance(operator, str) or operator not in _CONSTRAINT_OPERATORS:
        return _fail_or_drop("unsupported constraint operator", strict)

    if kind == "value":
        if set(active) != {"kind", "operator", "value", "unit"}:
            return _fail_or_drop(
                "value constraint requires kind, operator, value, and unit", strict
            )
        raw_value = active.get("value")
        unit = active.get("unit")
        if not _finite_number(raw_value) or float(raw_value) <= 0:
            return _fail_or_drop("value constraint requires a positive number", strict)
        if not isinstance(unit, str) or unit not in _VALUE_UNITS:
            return _fail_or_drop("unsupported value constraint unit", strict)
        number_value: int | float = (
            int(raw_value)
            if isinstance(raw_value, int) or float(raw_value).is_integer()
            else float(raw_value)
        )
        normalized: dict[str, object] = {
            "kind": "value",
            "operator": operator,
            "value": number_value,
            "unit": unit,
        }
        target_number = float(number_value)
    elif kind == "frequency":
        allowed = {"kind", "operator", "count", "period"}
        if "count" not in active and "value" in active:
            active = {**active, "count": active.pop("value")}
        if set(active) != allowed:
            return _fail_or_drop(
                "frequency constraint requires kind, operator, count, and period", strict
            )
        count = _positive_int(active.get("count"))
        period = active.get("period")
        if count is None:
            return _fail_or_drop("frequency count must be a positive integer", strict)
        if not isinstance(period, str) or period not in _FREQUENCY_PERIODS:
            return _fail_or_drop("unsupported frequency period", strict)
        normalized = {
            "kind": "frequency",
            "operator": operator,
            "count": count,
            "period": period,
        }
        target_number = float(count)
    else:
        if "day" not in active and "value" in active:
            active = {**active, "day": active.pop("value")}
        if not {"kind", "operator", "day"} <= set(active) or not (
            set(active) <= {"kind", "operator", "day", "month_offset"}
        ):
            return _fail_or_drop(
                "day_of_month constraint requires kind, operator, day, and optional month_offset",
                strict,
            )
        day = _positive_int(active.get("day"))
        raw_offset = active.get("month_offset", 0)
        offset = _non_negative_int(raw_offset)
        if day is None or not 1 <= day <= 31:
            return _fail_or_drop("day_of_month day must be an integer between 1 and 31", strict)
        if offset is None or offset > 12:
            return _fail_or_drop("day_of_month month_offset must be between 0 and 12", strict)
        normalized = {
            "kind": "day_of_month",
            "operator": operator,
            "day": day,
            "month_offset": offset,
        }
        target_number = float(day)

    if not strict and (constraint_text or source_quote):
        if not _matches_text(
            kind=kind,
            operator=operator,
            target_number=target_number,
            constraint_text=constraint_text,
            source_quote=source_quote,
        ):
            return None

    return normalized


def _fail_or_drop(message: str, strict: bool) -> None:
    if strict:
        raise RuleValidationError("invalid_rule_parameters", message)
    return None


def _matches_text(
    *,
    kind: str,
    operator: str,
    target_number: float,
    constraint_text: str,
    source_quote: str,
) -> bool:
    combined = f"{constraint_text} {source_quote}".casefold()
    numbers = _extract_numbers(combined)
    if not any(math.isclose(found, target_number, rel_tol=0.0, abs_tol=1e-6) for found in numbers):
        return False

    check_text = constraint_text.casefold() or combined
    has_lower = any(marker in check_text for marker in _LOWER_BOUND_MARKERS)
    has_upper = any(marker in check_text for marker in _UPPER_BOUND_MARKERS)
    if kind == "day_of_month" and "не позднее" in check_text:
        has_upper = True
    if has_lower and not has_upper and operator in {"lte", "lt"}:
        return False
    if has_upper and not has_lower and operator in {"gte", "gt"}:
        return False
    return True


def _extract_numbers(text: str) -> set[float]:
    found: set[float] = set()
    for match in re.findall(r"\d+(?:[.,]\d+)?", text):
        try:
            found.add(float(match.replace(",", ".")))
        except ValueError:
            continue
    for phrase, number in _NUMBER_WORDS:
        if re.search(rf"(?<![а-яёa-z]){re.escape(phrase)}(?![а-яёa-z])", text):
            found.add(float(number))
    return found


def validate_generated_rule(
    payload: dict[str, object],
    *,
    source_text: str,
    source_language: str,
    source_location: str = "",
    index: int,
) -> dict[str, object]:
    """Validate one provider result and return its normalized persistence shape."""
    if set(payload) - {"source_location"} != _FIELDS:
        raise RuleValidationError(
            "invalid_schema",
            f"generated rule #{index} must contain exactly the required fields",
        )
    for field in ("subject", "constraint_text", "condition", "severity", "source_quote"):
        if not isinstance(payload[field], str):
            raise RuleValidationError("invalid_schema", f"{field} must be a string")
    raw_constraint = payload["constraint_json"]
    if raw_constraint is not None and not isinstance(raw_constraint, dict):
        # A malformed structure is dropped rather than rejecting the textual rule.
        raw_constraint = None
    subject = payload["subject"].strip()
    constraint_text = payload["constraint_text"].strip()
    condition = payload["condition"].strip()
    quote = payload["source_quote"].strip()
    if not subject or not constraint_text or not quote:
        raise RuleValidationError("invalid_schema", "required rule fields cannot be empty")
    if payload["severity"] not in _SEVERITIES:
        raise RuleValidationError("invalid_schema", "unsupported severity")

    quote_matches = list(_find_quote_matches(source_text, quote))
    if not quote_matches:
        raise RuleValidationError("quote_not_found", "source_quote is not present in the chunk")
    if len(quote_matches) > 1:
        raise RuleValidationError("quote_not_found", "source_quote has ambiguous matches in the chunk")
    start, end = quote_matches[0]
    matched_quote = source_text[start:end]

    if source_language in {"ru", "en"}:
        _validate_language(payload, source_language)

    constraint_json = normalize_constraint_json(
        raw_constraint,
        constraint_text=constraint_text,
        source_quote=matched_quote,
        strict=False,
    )

    return {
        "subject": subject[:255],
        "constraint_text": constraint_text[:4000],
        "constraint_json": constraint_json,
        "condition": condition[:4000],
        "severity": payload["severity"],
        "source_quote": matched_quote,
        "source_location": source_location.strip(),
        "source_start": start,
        "source_end": end,
    }


_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")


def _find_quote_matches(source_text: str, quote: str) -> list[tuple[int, int]]:
    """Find a quote while treating whitespace runs as equivalent.

    A model sometimes joins a list lead-in and a list item with an ellipsis; such a quote matches the
    text from its first part to its last part.
    """
    pieces = []
    for piece in _ELLIPSIS.split(quote):
        words = [re.escape(word) for word in re.split(r"\s+", piece) if word]
        if words:
            pieces.append(r"\s+".join(words))
    if not pieces:
        return []
    pattern = re.compile(r"[\s\S]*?".join(pieces))
    return [(match.start(), match.end()) for match in pattern.finditer(source_text)]


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float) and value.is_integer() and value >= 1:
        return int(value)
    return None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _validate_language(payload: dict[str, object], source_language: str) -> None:
    for field in _LANGUAGE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str):
            continue
        letters = "".join(char for char in value if char.isalpha())
        if not letters:
            continue
        detected = detect_source_language(value)
        if detected != source_language:
            raise RuleValidationError(
                "language_mismatch",
                f"{field} language does not match source language {source_language}",
            )
