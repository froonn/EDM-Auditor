"""Validation and normalization for model-generated audit rules."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .audit_engine.validators import _date_parameter
from .model_config import detect_source_language


_FIELDS = {
    "rule_code",
    "name",
    "description",
    "severity",
    "check_type",
    "parameters",
    "source_quote",
    "source_location",
}
_PARAMETER_FIELDS = {
    "min_days", "max_days", "entity", "min", "max", "before", "after",
    "keywords", "mode", "match", "pattern", "query", "k", "threshold",
    "recommendation",
}
_CHECK_TYPES = {"keyword", "regex", "numeric", "date", "duration", "semantic"}
_SEVERITIES = {"low", "medium", "high", "critical"}
_LANGUAGE_FIELDS = ("name", "description", "source_quote")


@dataclass(frozen=True)
class RuleValidationError(ValueError):
    """A rejected generated rule with a stable machine-readable category."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_generated_rule(
    payload: dict[str, object],
    *,
    source_text: str,
    source_language: str,
    source_location: str,
    index: int,
) -> dict[str, object]:
    """Validate one provider result and return its normalized persistence shape."""
    if set(payload) != _FIELDS:
        raise RuleValidationError(
            "invalid_schema",
            f"generated rule #{index} must contain exactly the required fields",
        )
    for field in ("rule_code", "name", "description", "severity", "check_type",
                  "source_quote", "source_location"):
        if not isinstance(payload[field], str):
            raise RuleValidationError("invalid_schema", f"{field} must be a string")
    parameters = payload["parameters"]
    if not isinstance(parameters, dict):
        raise RuleValidationError("invalid_schema", "parameters must be an object")
    if not all(isinstance(key, str) for key in parameters):
        raise RuleValidationError("invalid_schema", "parameter names must be strings")

    rule_code = payload["rule_code"].strip()
    name = payload["name"].strip()
    description = payload["description"].strip()
    quote = payload["source_quote"].strip()
    location = payload["source_location"].strip()
    check_type = payload["check_type"]
    if not rule_code or not name or not description or not quote or not location:
        raise RuleValidationError("invalid_schema", "required rule fields cannot be empty")
    if payload["severity"] not in _SEVERITIES:
        raise RuleValidationError("invalid_schema", "unsupported severity")
    if check_type not in _CHECK_TYPES:
        raise RuleValidationError("unsupported_check_type", f"unsupported check type: {check_type}")
    if location != source_location:
        raise RuleValidationError("invalid_schema", "source_location does not match the chunk")
    if set(parameters) - _PARAMETER_FIELDS:
        raise RuleValidationError("invalid_parameters", "parameters contain unsupported fields")

    quote_matches = list(_find_quote_matches(source_text, quote))
    if not quote_matches:
        raise RuleValidationError("quote_not_found", "source_quote is not present in the chunk")
    if len(quote_matches) > 1:
        raise RuleValidationError("quote_not_found", "source_quote has ambiguous matches in the chunk")
    start, end = quote_matches[0]

    _validate_parameters(check_type, parameters)
    if source_language in {"ru", "en"}:
        _validate_language(payload, parameters, source_language)

    return {
        "rule_code": rule_code[:100],
        "name": name[:255],
        "severity": payload["severity"],
        "description": description[:4000],
        "check_type": check_type,
        "parameters_json": json.dumps(parameters, ensure_ascii=False, sort_keys=True),
        "source_quote": source_text[start:end],
        "source_location": location,
        "source_start": start,
        "source_end": end,
    }


def _find_quote_matches(source_text: str, quote: str) -> list[tuple[int, int]]:
    """Find a quote while treating whitespace runs as equivalent."""
    parts = [re.escape(part) for part in re.split(r"\s+", quote) if part]
    if not parts:
        return []
    pattern = re.compile(r"\s+".join(parts))
    return [(match.start(), match.end()) for match in pattern.finditer(source_text)]


def _validate_parameters(check_type: str, parameters: dict[str, Any]) -> None:
    allowed: dict[str, set[str]] = {
        "duration": {"min_days", "max_days"},
        "numeric": {"entity", "min", "max"},
        "date": {"before", "after"},
        "keyword": {"keywords", "mode", "match"},
        "regex": {"pattern"},
        "semantic": {"query", "k", "threshold"},
    }
    if set(parameters) - allowed[check_type]:
        raise RuleValidationError("invalid_parameters", f"invalid parameters for {check_type}")
    if check_type == "duration":
        _require_any(parameters, "min_days", "max_days")
        _numbers(parameters, "min_days", "max_days", integer=True)
    elif check_type == "numeric":
        _require_any(parameters, "min", "max")
        if parameters.get("entity") not in {"number", "duration", "money", "percent"}:
            raise RuleValidationError("invalid_parameters", "numeric entity is invalid")
        _numbers(parameters, "min", "max")
    elif check_type == "date":
        _require_any(parameters, "before", "after")
        for key in ("before", "after"):
            if key in parameters:
                try:
                    _date_parameter(parameters[key], key)
                except ValueError as exc:
                    raise RuleValidationError("invalid_parameters", str(exc)) from exc
    elif check_type == "keyword":
        keywords = parameters.get("keywords")
        if not isinstance(keywords, list) or not keywords or not all(
            isinstance(item, str) and item.strip() for item in keywords
        ):
            raise RuleValidationError("invalid_parameters", "keywords must be non-empty strings")
        if parameters.get("mode", "forbidden") not in {"forbidden", "required"}:
            raise RuleValidationError("invalid_parameters", "keyword mode is invalid")
        if parameters.get("match", "literal") not in {"literal", "stem", "regex"}:
            raise RuleValidationError("invalid_parameters", "keyword match is invalid")
    elif check_type == "regex":
        pattern = parameters.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise RuleValidationError("invalid_parameters", "regex pattern is required")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleValidationError("invalid_parameters", f"invalid regex: {exc}") from exc
    else:
        query = parameters.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RuleValidationError("invalid_parameters", "semantic query is required")
        if "k" in parameters and (
            isinstance(parameters["k"], bool)
            or not isinstance(parameters["k"], int)
            or parameters["k"] <= 0
        ):
            raise RuleValidationError("invalid_parameters", "semantic k must be positive")
        if "threshold" in parameters and not _finite_number(parameters["threshold"]):
            raise RuleValidationError("invalid_parameters", "semantic threshold must be numeric")


def _require_any(parameters: dict[str, Any], *names: str) -> None:
    if not any(name in parameters and parameters[name] is not None for name in names):
        raise RuleValidationError("invalid_parameters", f"one of {names} is required")


def _numbers(parameters: dict[str, Any], *names: str, integer: bool = False) -> None:
    for name in names:
        if name not in parameters:
            continue
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuleValidationError("invalid_parameters", f"{name} must be numeric")
        if integer and not isinstance(value, int):
            raise RuleValidationError("invalid_parameters", f"{name} must be an integer")
        if not math.isfinite(value):
            raise RuleValidationError("invalid_parameters", f"{name} must be finite")


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _validate_language(
    payload: dict[str, object], parameters: dict[str, Any], source_language: str
) -> None:
    values: list[tuple[str, object]] = [(field, payload[field]) for field in _LANGUAGE_FIELDS]
    if isinstance(parameters.get("keywords"), list):
        values.extend(("keywords", value) for value in parameters["keywords"])
    for field in ("query",):
        if field in parameters:
            values.append((field, parameters[field]))
    for field, value in values:
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
