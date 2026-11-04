"""Contracts for rule applicability and audit rule selection."""

from enum import StrEnum


class ApplicabilityScope(StrEnum):
    UNIVERSAL = "universal"
    TYPED = "typed"
    MANUAL_ONLY = "manual_only"
    UNKNOWN = "unknown"
