"""Errors raised by the deterministic audit engine."""


class AuditEngineError(Exception):
    """Base class for audit engine errors."""


class InvalidRuleConfiguration(AuditEngineError, ValueError):
    """Raised when a rule contains invalid parameters."""


class FindingRangeError(AuditEngineError, ValueError):
    """Raised when a finding points outside the audited document."""
