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
_STATEMENT_FIELDS = {
    "subject",
    "statement_text",
    "constraint_json",
    "source_quote",
}
_SEVERITIES = {"low", "medium", "high", "critical"}
_LANGUAGE_FIELDS = ("subject", "constraint_text", "condition", "source_quote")
_STATEMENT_LANGUAGE_FIELDS = ("subject", "statement_text", "source_quote")

_CONSTRAINT_KINDS = {"value", "frequency", "day_of_month"}
_CONSTRAINT_OPERATORS = {"gte", "lte", "gt", "lt", "eq"}
_VALUE_UNITS = {"day", "hour", "byn", "%"}
_UNIT_ALIASES: dict[str, tuple[str, float]] = {
    "day": ("day", 1.0),
    "days": ("day", 1.0),
    "день": ("day", 1.0),
    "дня": ("day", 1.0),
    "дней": ("day", 1.0),
    "week": ("day", 7.0),
    "weeks": ("day", 7.0),
    "неделя": ("day", 7.0),
    "недели": ("day", 7.0),
    "недель": ("day", 7.0),
    "month": ("day", 30.0),
    "months": ("day", 30.0),
    "месяц": ("day", 30.0),
    "месяца": ("day", 30.0),
    "месяцев": ("day", 30.0),
    "year": ("day", 365.0),
    "years": ("day", 365.0),
    "год": ("day", 365.0),
    "года": ("day", 365.0),
    "лет": ("day", 365.0),
    "hour": ("hour", 1.0),
    "hours": ("hour", 1.0),
    "час": ("hour", 1.0),
    "часа": ("hour", 1.0),
    "часов": ("hour", 1.0),
    "byn": ("byn", 1.0),
    "руб": ("byn", 1.0),
    "рубль": ("byn", 1.0),
    "рубля": ("byn", 1.0),
    "рублей": ("byn", 1.0),
    "р.": ("byn", 1.0),
    "%": ("%", 1.0),
    "percent": ("%", 1.0),
    "процент": ("%", 1.0),
    "процента": ("%", 1.0),
    "процентов": ("%", 1.0),
}
_FREQUENCY_PERIODS = {"month", "year"}
_PERIOD_ALIASES: dict[str, str] = {
    "month": "month",
    "months": "month",
    "месяц": "month",
    "year": "year",
    "years": "year",
    "год": "year",
}

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
    ("две", 2),
    ("двух", 2),
    ("двое", 2),
    ("дважды", 2),
    ("полтора", 1.5),
    ("один", 1),
    ("одна", 1),
    ("одну", 1),
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

    When ``strict`` is False (for model-generated rules and document statements), an invalid
    structure or a structure that contradicts the text is dropped (returns ``None``) so the item
    stays textual instead of being rejected.
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
    if not strict and operator is None:
        operator = "eq"
        active["operator"] = "eq"
    if not isinstance(operator, str) or operator not in _CONSTRAINT_OPERATORS:
        return _fail_or_drop("unsupported constraint operator", strict)

    combined_text = f"{constraint_text} {source_quote}".casefold()

    if kind == "value":
        if set(active) != {"kind", "operator", "value", "unit"}:
            return _fail_or_drop(
                "value constraint requires kind, operator, value, and unit", strict
            )
        raw_value = active.get("value")
        raw_unit = active.get("unit")
        if not _finite_number(raw_value) or float(raw_value) <= 0:
            return _fail_or_drop("value constraint requires a positive number", strict)
        if not isinstance(raw_unit, str):
            return _fail_or_drop("unsupported value constraint unit", strict)
        if strict:
            if raw_unit not in _VALUE_UNITS:
                return _fail_or_drop("unsupported value constraint unit", strict)
            unit = raw_unit
            scale = 1.0
        else:
            alias = _UNIT_ALIASES.get(raw_unit.strip().casefold())
            if alias is None:
                return None
            unit, scale = alias
        raw_scaled = float(raw_value) * scale
        if unit == "day" and math.isclose(scale, 1.0) and combined_text:
            raw_scaled = _rescale_day_value_from_text(raw_scaled, combined_text)
        number_value: int | float = (
            int(round(raw_scaled))
            if float(raw_scaled).is_integer() or math.isclose(raw_scaled, round(raw_scaled), abs_tol=1e-6)
            else float(raw_scaled)
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
        raw_period = active.get("period")
        if count is None:
            return _fail_or_drop("frequency count must be a positive integer", strict)
        if not isinstance(raw_period, str):
            return _fail_or_drop("unsupported frequency period", strict)
        if strict:
            if raw_period not in _FREQUENCY_PERIODS:
                return _fail_or_drop("unsupported frequency period", strict)
            period = raw_period
        else:
            period = _PERIOD_ALIASES.get(raw_period.strip().casefold(), "")
            if period not in _FREQUENCY_PERIODS:
                return None
        normalized = {
            "kind": "frequency",
            "operator": operator,
            "count": count,
            "period": period,
        }
        target_number = float(count)
    else:
        if not strict and re.search(
            r"\b\d{1,2}\s+и\s+\d{1,2}\s*(?:-го)?\s+числа\s+(?:каждого\s+)?месяца",
            combined_text,
        ):
            kind = "frequency"
            operator = "eq"
            normalized = {
                "kind": "frequency",
                "operator": "eq",
                "count": 2,
                "period": "month",
            }
            target_number = 2.0
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
            raw_offset = active.get("month_offset")
            if raw_offset is None:
                offset: int | None = (
                    1
                    if not strict and _has_next_month_phrase(combined_text)
                    else 0
                )
            else:
                offset = _non_negative_int(raw_offset)
            if day is None or not 1 <= day <= 31:
                return _fail_or_drop("day_of_month day must be an integer between 1 and 31", strict)
            if offset is None or offset > 12:
                return _fail_or_drop("day_of_month month_offset must be between 0 and 12", strict)
            if not strict and offset == 0 and _has_next_month_phrase(combined_text):
                offset = 1
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


def _has_next_month_phrase(text: str) -> bool:
    return bool(
        re.search(
            r"следующего\s+месяца|месяца\s*,\s*следующего\s+за|next\s+month|following\s+month",
            text,
            re.IGNORECASE,
        )
    )


def _rescale_day_value_from_text(value: float, text: str) -> float:
    """Convert raw week/month/year counts to days when the model kept unit='day'."""
    for unit_pattern, factor in (
        (r"недел(?:и|ь|я|ю|е)?|weeks?", 7.0),
        (r"месяц(?:а|ев|ем|е)?|months?", 30.0),
        (r"лет|год(?:а|ов|у|ом)?|years?", 365.0),
    ):
        for match in re.finditer(
            rf"(?<![а-яёa-z\d])(\d+(?:[.,]\d+)?)\s*(?:[а-яёa-z-]+\s+){{0,2}}(?:{unit_pattern})(?![а-яёa-z])",
            text,
        ):
            num = float(match.group(1).replace(",", "."))
            if math.isclose(num, value, rel_tol=0.0, abs_tol=1e-6):
                return value * factor
        for phrase, num in _NUMBER_WORDS:
            if math.isclose(float(num), value, rel_tol=0.0, abs_tol=1e-6):
                if re.search(
                    rf"(?<![а-яёa-z]){re.escape(phrase)}\s+(?:[а-яёa-z-]+\s+){{0,2}}(?:{unit_pattern})(?![а-яёa-z])",
                    text,
                ):
                    return value * factor
    return value


def parse_constraint_from_text(
    text: str,
    *,
    default_operator: str = "eq",
) -> dict[str, object] | None:
    """Derive a normalized constraint structure from a rule or statement phrase."""
    lowered = text.casefold()
    if not lowered.strip():
        return None
    has_lower = any(marker in lowered for marker in _LOWER_BOUND_MARKERS)
    has_upper = any(marker in lowered for marker in _UPPER_BOUND_MARKERS)
    if "не позднее" in lowered and "не позднее чем за" not in lowered:
        has_upper = True
    operator = (
        "gte"
        if has_lower and not has_upper
        else "lte"
        if has_upper and not has_lower
        else default_operator
    )

    freq_match = re.search(
        r"(?<![а-яёa-z])(один|одного|два|двух|три|трех|трёх|четыре|четырех|четырёх|\d+)\s+раз(?:а)?\s+в\s+(месяц|год)(?![а-яёa-z])",
        lowered,
    )
    if freq_match:
        raw_count = freq_match.group(1)
        period = "month" if freq_match.group(2) == "месяц" else "year"
        word_counts = dict(_NUMBER_WORDS)
        count = int(word_counts[raw_count]) if raw_count in word_counts else int(raw_count)
        return {
            "kind": "frequency",
            "operator": operator,
            "count": count,
            "period": period,
        }
    if re.search(r"(?<![а-яёa-z])дважды\s+в\s+(месяц|год)(?![а-яёa-z])", lowered):
        period_word = re.search(r"дважды\s+в\s+(месяц|год)", lowered).group(1)
        return {
            "kind": "frequency",
            "operator": operator,
            "count": 2,
            "period": "month" if period_word == "месяц" else "year",
        }
    if re.search(
        r"\b\d{1,2}\s+и\s+\d{1,2}\s*(?:-го)?\s+числа\s+(?:каждого\s+)?месяца\b",
        lowered,
    ):
        return {
            "kind": "frequency",
            "operator": operator,
            "count": 2,
            "period": "month",
        }

    dom_match = re.search(
        r"\b(\d{1,2})\s*(?:-го)?\s+числа(?:\s+(?:месяца\s*,\s*)?следующего(?:\s+за\s+[а-яё]+)?(?:\s+месяца)?)?",
        lowered,
    )
    if dom_match:
        day = int(dom_match.group(1))
        if 1 <= day <= 31:
            dom_op = (
                "lte"
                if ("не позднее" in lowered or re.search(r"\bдо\s+\d{1,2}", lowered))
                and not has_lower
                else operator
            )
            return {
                "kind": "day_of_month",
                "operator": dom_op,
                "day": day,
                "month_offset": 1 if _has_next_month_phrase(lowered) else 0,
            }

    for pattern, unit, scale in (
        (
            r"(\d+(?:[.,]\d+)?)\s*(?:[а-яёa-z-]+\s+){0,2}(дн(?:я|ей)?|день|days?)(?![а-яёa-z])",
            "day",
            1.0,
        ),
        (
            r"(\d+(?:[.,]\d+)?)\s*(?:[а-яёa-z-]+\s+){0,2}(недел(?:и|ь|я|ю)?|weeks?)(?![а-яёa-z])",
            "day",
            7.0,
        ),
        (
            r"(\d+(?:[.,]\d+)?)\s*(?:[а-яёa-z-]+\s+){0,2}(месяц(?:а|ев)?|months?)(?![а-яёa-z])",
            "day",
            30.0,
        ),
        (
            r"(\d+(?:[.,]\d+)?)\s*(?:[а-яёa-z-]+\s+){0,2}(лет|год(?:а|ов)?|years?)(?![а-яёa-z])",
            "day",
            365.0,
        ),
        (
            r"(\d+(?:[.,]\d+)?)\s*(?:[а-яёa-z-]+\s+){0,2}(час(?:а|ов)?|hours?)(?![а-яёa-z])",
            "hour",
            1.0,
        ),
        (
            r"(\d+(?:[.,]\d+)?)\s*(руб(?:лей|ля|ль)?|byn|р\.)(?![а-яёa-z])",
            "byn",
            1.0,
        ),
        (
            r"(\d+(?:[.,]\d+)?)\s*(%|процент(?:а|ов)?)(?![а-яёa-z])",
            "%",
            1.0,
        ),
    ):
        val_match = re.search(pattern, lowered)
        if val_match:
            if unit == "day" and re.match(r"\s*числ", lowered[val_match.start() :]):
                continue
            raw_amount = float(val_match.group(1).replace(",", ".")) * scale
            amount: int | float = (
                int(round(raw_amount))
                if raw_amount.is_integer() or math.isclose(raw_amount, round(raw_amount), abs_tol=1e-6)
                else raw_amount
            )
            return {
                "kind": "value",
                "operator": operator,
                "value": amount,
                "unit": unit,
            }

    for phrase, word_num in _NUMBER_WORDS:
        for unit_rx, unit, scale in (
            (r"дн(?:я|ей)?|день|days?", "day", 1.0),
            (r"недел(?:и|ь|я|ю)?|weeks?", "day", 7.0),
            (r"месяц(?:а|ев)?|months?", "day", 30.0),
            (r"лет|год(?:а|ов)?|years?", "day", 365.0),
            (r"час(?:а|ов)?|hours?", "hour", 1.0),
            (r"руб(?:лей|ля|ль)?|byn", "byn", 1.0),
            (r"процент(?:а|ов)?", "%", 1.0),
        ):
            if re.search(
                rf"(?<![а-яёa-z]){re.escape(phrase)}\s+(?:[а-яёa-z-]+\s+){{0,2}}(?:{unit_rx})(?![а-яёa-z])",
                lowered,
            ):
                raw_amount = float(word_num) * scale
                amount = (
                    int(round(raw_amount))
                    if raw_amount.is_integer() or math.isclose(raw_amount, round(raw_amount), abs_tol=1e-6)
                    else raw_amount
                )
                return {
                    "kind": "value",
                    "operator": operator,
                    "value": amount,
                    "unit": unit,
                }
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
    if kind == "frequency" and target_number == 2 and re.search(
        r"\b\d{1,2}\s+и\s+\d{1,2}\s*(?:-го)?\s+числа", combined
    ):
        numbers.add(2.0)
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
    raw_numbers: list[float] = []
    for match in re.findall(r"\d+(?:[.,]\d+)?", text):
        try:
            num = float(match.replace(",", "."))
            found.add(num)
            raw_numbers.append(num)
        except ValueError:
            continue
    for phrase, number in _NUMBER_WORDS:
        if re.search(rf"(?<![а-яёa-z]){re.escape(phrase)}(?![а-яёa-z])", text):
            num = float(number)
            found.add(num)
            raw_numbers.append(num)
    if re.search(r"недел(?:и|ь|я|ю|е)?|weeks?", text):
        found.update(num * 7.0 for num in raw_numbers)
    if re.search(r"месяц(?:а|ев|ем|е)?|months?", text):
        found.update(num * 30.0 for num in raw_numbers)
    if re.search(r"лет|год(?:а|ов|у|ом)?|years?", text):
        found.update(num * 365.0 for num in raw_numbers)
    if "половину" in text or "половина" in text:
        found.add(50.0)
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


def validate_generated_statement(
    payload: dict[str, object],
    *,
    source_text: str,
    source_language: str = "auto",
    index: int = 1,
) -> dict[str, object]:
    """Validate one model-extracted document statement and resolve its character offsets."""
    if not isinstance(payload, dict) or not (_STATEMENT_FIELDS <= set(payload)):
        raise RuleValidationError(
            "invalid_schema",
            f"generated statement #{index} must contain the required statement fields",
        )
    for field in ("subject", "statement_text", "source_quote"):
        if not isinstance(payload.get(field), str):
            raise RuleValidationError("invalid_schema", f"{field} must be a string")
    raw_constraint = payload.get("constraint_json")
    if raw_constraint is not None and not isinstance(raw_constraint, dict):
        raw_constraint = None

    subject = str(payload["subject"]).strip()
    statement_text = str(payload["statement_text"]).strip()
    quote = str(payload["source_quote"]).strip()
    if not subject or not statement_text or not quote:
        raise RuleValidationError("invalid_schema", "required statement fields cannot be empty")

    quote_matches = list(_find_quote_matches(source_text, quote))
    if not quote_matches:
        raise RuleValidationError("quote_not_found", "source_quote is not present in the chunk")
    if len(quote_matches) > 1:
        raise RuleValidationError(
            "quote_not_found", "source_quote has ambiguous matches in the chunk"
        )
    start, end = quote_matches[0]
    matched_quote = source_text[start:end]

    if source_language in {"ru", "en"}:
        _validate_language(payload, source_language, fields=_STATEMENT_LANGUAGE_FIELDS)

    constraint_json = normalize_constraint_json(
        raw_constraint,
        constraint_text=statement_text,
        source_quote=matched_quote,
        strict=False,
    )

    return {
        "subject": subject[:255],
        "statement_text": statement_text[:4000],
        "constraint_json": constraint_json,
        "source_quote": matched_quote,
        "start_char": start,
        "end_char": end,
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


def _validate_language(
    payload: dict[str, object],
    source_language: str,
    *,
    fields: tuple[str, ...] = _LANGUAGE_FIELDS,
) -> None:
    for field in fields:
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
