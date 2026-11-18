"""Deterministic validators for structured stage 2 rule constraints."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import math
import re
from typing import Any

from edm_auditor.rule_validation import (
    RuleValidationError,
    parse_constraint_from_text,
    validate_manual_constraint,
)

from .exceptions import InvalidRuleConfiguration
from .models import ExtractedEntity, FindingDraft, RuleSpec, StatementSpec

_FREQUENCY_WORDS = {
    "один": 1,
    "одного": 1,
    "1": 1,
    "два": 2,
    "двух": 2,
    "2": 2,
    "три": 3,
    "трех": 3,
    "трёх": 3,
    "3": 3,
    "четыре": 4,
    "4": 4,
}
_FREQUENCY_PATTERN = re.compile(
    r"\b(один|одного|два|двух|три|трех|трёх|четыре|\d+)\s+раз(?:а)?\s+в\s+(месяц|год)",
    re.IGNORECASE,
)
_DAY_OF_MONTH_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:-го)?\s+числа(?:\s+следующего\s+месяца)?",
    re.IGNORECASE,
)


def validate_rule(
    rule: RuleSpec,
    text: str,
    entities: Iterable[ExtractedEntity] = (),
    statements: Iterable[StatementSpec] = (),
) -> tuple[FindingDraft, ...]:
    """Evaluate a rule's structured constraint against document statements, entities, and text."""
    if not rule.is_active or rule.constraint_json is None:
        return ()
    try:
        constraint = validate_manual_constraint(rule.constraint_json)
    except RuleValidationError as exc:
        raise InvalidRuleConfiguration(str(exc)) from exc
    if constraint is None:
        return ()

    kind = str(constraint["kind"])
    operator = str(constraint["operator"])
    entity_tuple = tuple(entities)
    statement_tuple = tuple(statements)

    statement_findings = _statement_findings(rule, text, statement_tuple, constraint)

    if kind == "value":
        target = float(constraint["value"])
        unit = str(constraint["unit"])
        if unit == "day":
            base = _day_value_findings(rule, text, entity_tuple, operator, target)
            return (*statement_findings, *base)
        entity_kind = {"byn": "money", "%": "percent", "hour": "number"}[unit]
        base = _numeric_entity_findings(
            rule, text, entity_tuple, entity_kind, operator, target
        )
        return (*statement_findings, *base)
    if kind == "frequency":
        base = _frequency_findings(
            rule,
            text,
            operator=operator,
            target=float(constraint["count"]),
            period=str(constraint["period"]),
        )
        return (*statement_findings, *base)
    if kind == "day_of_month":
        base = _day_of_month_findings(
            rule,
            text,
            operator=operator,
            target=float(constraint["day"]),
        )
        return (*statement_findings, *base)
    raise InvalidRuleConfiguration(f"unsupported constraint kind: {kind}")


def _statement_findings(
    rule: RuleSpec,
    text: str,
    statements: tuple[StatementSpec, ...],
    rule_constraint: dict[str, object],
) -> tuple[FindingDraft, ...]:
    if not statements:
        return ()
    kind = str(rule_constraint["kind"])
    operator = str(rule_constraint["operator"])
    findings: list[FindingDraft] = []
    for statement in statements:
        stmt_constraint = statement.constraint_json or parse_constraint_from_text(
            f"{statement.statement_text} {statement.source_quote}"
        )
        if not isinstance(stmt_constraint, dict) or stmt_constraint.get("kind") != kind:
            continue
        if kind == "value":
            if stmt_constraint.get("unit") != rule_constraint["unit"]:
                continue
            actual = float(stmt_constraint["value"])
            target = float(rule_constraint["value"])
        elif kind == "frequency":
            if stmt_constraint.get("period") != rule_constraint["period"]:
                continue
            actual = float(stmt_constraint["count"])
            target = float(rule_constraint["count"])
        elif kind == "day_of_month":
            actual = float(stmt_constraint["day"])
            target = float(rule_constraint["day"])
        else:
            continue
        if not _satisfies(actual, operator, target):
            findings.append(_draft(rule, text, statement.start_char, statement.end_char))
    return tuple(findings)


def _satisfies(actual: float, operator: str, target: float) -> bool:
    if operator == "gte":
        return actual >= target
    if operator == "gt":
        return actual > target
    if operator == "lte":
        return actual <= target
    if operator == "lt":
        return actual < target
    if operator == "eq":
        return math.isclose(actual, target, rel_tol=0.0, abs_tol=1e-6)
    raise InvalidRuleConfiguration(f"unsupported operator: {operator}")


def _numeric_entity_findings(
    rule: RuleSpec,
    text: str,
    entities: tuple[ExtractedEntity, ...],
    entity_kind: str,
    operator: str,
    target: float,
) -> tuple[FindingDraft, ...]:
    findings: list[FindingDraft] = []
    for entity in entities:
        if entity.kind != entity_kind:
            continue
        value_match = re.search(r"\d+(?:[.,]\d+)?", entity.value)
        if value_match is None:
            continue
        value = float(value_match.group().replace(",", "."))
        if not _satisfies(value, operator, target):
            findings.append(_draft(rule, text, entity.start_char, entity.end_char))
    return tuple(findings)


def _day_value_findings(
    rule: RuleSpec,
    text: str,
    entities: tuple[ExtractedEntity, ...],
    operator: str,
    target: float,
) -> tuple[FindingDraft, ...]:
    findings: list[FindingDraft] = []
    duration_entities = [entity for entity in entities if entity.kind == "duration"]
    if not duration_entities:
        findings.extend(_date_interval_findings(rule, text, entities, operator, target))
    for entity in duration_entities:
        value = _duration_days(entity.value)
        if not _satisfies(value, operator, target):
            findings.append(_draft(rule, text, entity.start_char, entity.end_char))
    return tuple(findings)


def _date_interval_findings(
    rule: RuleSpec,
    text: str,
    entities: tuple[ExtractedEntity, ...],
    operator: str,
    target: float,
) -> tuple[FindingDraft, ...]:
    dates = [entity for entity in entities if entity.kind == "date"]
    findings: list[FindingDraft] = []
    for start_entity, end_entity in zip(dates, dates[1:]):
        delta = float(abs((_parse_date(end_entity.value) - _parse_date(start_entity.value)).days))
        if not _satisfies(delta, operator, target):
            start = min(start_entity.start_char, end_entity.start_char)
            end = max(start_entity.end_char, end_entity.end_char)
            findings.append(_draft(rule, text, start, end))
    return tuple(findings)


def _frequency_findings(
    rule: RuleSpec,
    text: str,
    *,
    operator: str,
    target: float,
    period: str,
) -> tuple[FindingDraft, ...]:
    expected_period = "месяц" if period == "month" else "год"
    findings: list[FindingDraft] = []
    for match in _FREQUENCY_PATTERN.finditer(text):
        raw_count, raw_period = match.group(1).casefold(), match.group(2).casefold()
        if raw_period != expected_period:
            continue
        actual = float(
            _FREQUENCY_WORDS[raw_count] if raw_count in _FREQUENCY_WORDS else int(raw_count)
        )
        if not _satisfies(actual, operator, target):
            findings.append(_draft(rule, text, match.start(), match.end()))
    return tuple(findings)


def _day_of_month_findings(
    rule: RuleSpec,
    text: str,
    *,
    operator: str,
    target: float,
) -> tuple[FindingDraft, ...]:
    findings: list[FindingDraft] = []
    for match in _DAY_OF_MONTH_PATTERN.finditer(text):
        actual = float(int(match.group(1)))
        if not _satisfies(actual, operator, target):
            findings.append(_draft(rule, text, match.start(), match.end()))
    return tuple(findings)


def _parse_date(value: str) -> date:
    normalized = value.casefold()
    month_names = (
        "января февраля марта апреля мая июня июля августа сентября октября ноября декабря"
    ).split()
    match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", normalized)
    if match:
        year = int(match.group(3))
        return date(year + 2000 if year < 100 else year, int(match.group(2)), int(match.group(1)))
    match = re.fullmatch(r"(\d{1,2})\s+([а-я]+)\s+(\d{4})", normalized)
    if match and match.group(2) in month_names:
        return date(int(match.group(3)), month_names.index(match.group(2)) + 1, int(match.group(1)))
    raise InvalidRuleConfiguration(f"unsupported date value: {value}")


def _duration_days(value: str) -> float:
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:[а-яa-z-]+\s+){0,3}"
        r"(дн(?:я|ей)?|день|месяц(?:а|ев)?|лет?|год(?:а|ов)?|days?)",
        value.casefold(),
    )
    if match is None:
        raise InvalidRuleConfiguration(f"unsupported duration value: {value}")
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    if unit.startswith("месяц"):
        return amount * 30
    if unit.startswith(("лет", "год")):
        return amount * 365
    return amount


def _draft(
    rule: RuleSpec, text: str, start: int | None, end: int | None
) -> FindingDraft:
    quote = text[start:end] if start is not None and end is not None else None
    description = rule.constraint_text or rule.subject
    return FindingDraft(
        rule_id=rule.rule_id,
        rule_code=rule.rule_code,
        severity=rule.severity,
        description=description,
        start_char=start,
        end_char=end,
        quote=quote,
        recommendation=None,
        legal_act_id=rule.legal_act_id,
        deduplication_key=f"{rule.rule_code}:{start}:{end}:{description}",
        norm_quote=rule.source_quote,
        rule_name=rule.subject,
        requires_confirmation=True,
    )
