"""Errors raised by the neural analysis layer."""


class NeuralAnalysisError(ValueError):
    """Base error for provider and response validation failures."""


class InvalidNeuralResponse(NeuralAnalysisError):
    """The provider response does not satisfy the application contract."""


class AuditModelError(RuntimeError):
    """A model required by the audit did not produce a usable result."""
