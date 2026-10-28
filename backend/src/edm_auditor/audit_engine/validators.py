"""Deterministic validators for audit rules."""

import re
from collections.abc import Iterable
from typing import Any

from .exceptions import InvalidRuleConfiguration
from .models import ExtractedEntity, FindingDraft, RuleSpec


def validate_rule(
    rule: RuleSpec,
    text: str,
    entities: Iterable[ExtractedEntity] = (),
) -> tuple[FindingDraft, ...]:
    """Evaluate one rule and return source-preserving findings."""
    if not rule.is_active:
        return ()
    if rule.check_type == "keyword":
        return _keyword_findings(rule, text)
    if rule.check_type == "regex":
        return _regex_findings(rule, text)
    if rule.check_type == "semantic":
        return ()
    if rule.check_type == "numeric":
        return _numeric_findings(rule, text, tuple(entities))
    raise InvalidRuleConfiguration(f"unsupported check type: {rule.check_type}")


def _keyword_findings(rule: RuleSpec, text: str) -> tuple[FindingDraft, ...]:
    keywords = rule.parameters.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, list) or not all(isinstance(item, str) and item for item in keywords):
        raise InvalidRuleConfiguration("keyword rule requires a non-empty 'keywords' list")
    findings = []
    for keyword in keywords:
        for match in re.finditer(re.escape(keyword), text, re.IGNORECASE):
            findings.append(_draft(rule, text, match.start(), match.end()))
    return tuple(findings)


def _regex_findings(rule: RuleSpec, text: str) -> tuple[FindingDraft, ...]:
    pattern = rule.parameters.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise InvalidRuleConfiguration("regex rule requires a non-empty 'pattern'")
    try:
        matches = re.finditer(pattern, text, re.IGNORECASE)
    except re.error as exc:
        raise InvalidRuleConfiguration(f"invalid regex: {exc}") from exc
    return tuple(_draft(rule, text, match.start(), match.end()) for match in matches)


def _numeric_findings(
    rule: RuleSpec,
    text: str,
    entities: tuple[ExtractedEntity, ...],
) -> tuple[FindingDraft, ...]:
    kind = rule.parameters.get("entity", "number")
    minimum = rule.parameters.get("min")
    maximum = rule.parameters.get("max")
    if kind not in {"number", "duration", "money", "percent"}:
        raise InvalidRuleConfiguration(f"unsupported numeric entity: {kind}")
    if minimum is None and maximum is None:
        raise InvalidRuleConfiguration("numeric rule requires 'min' or 'max'")
    findings = []
    for entity in entities:
        if entity.kind != kind:
            continue
        value_match = re.search(r"\d+(?:[.,]\d+)?", entity.value)
        if value_match is None:
            continue
        value = float(value_match.group().replace(",", "."))
        violates = (minimum is not None and value < _number(minimum)) or (
            maximum is not None and value > _number(maximum)
        )
        if violates:
            findings.append(_draft(rule, text, entity.start_char, entity.end_char))
    return tuple(findings)


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise InvalidRuleConfiguration("numeric limits must be numbers")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRuleConfiguration("numeric limits must be numbers") from exc


def _draft(rule: RuleSpec, text: str, start: int, end: int) -> FindingDraft:
    quote = text[start:end]
    description = rule.description or rule.name
    return FindingDraft(
        rule_id=rule.rule_id,
        rule_code=rule.rule_code,
        severity=rule.severity,
        description=description,
        start_char=start,
        end_char=end,
        quote=quote,
        recommendation=rule.parameters.get("recommendation"),
        legal_act_id=rule.legal_act_id,
        deduplication_key=f"{rule.rule_code}:{start}:{end}:{description}",
    )
