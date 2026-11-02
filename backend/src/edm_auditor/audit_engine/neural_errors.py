"""Errors raised by the optional neural analysis layer."""


class NeuralAnalysisError(ValueError):
    """Base error for provider and response validation failures."""


class InvalidNeuralResponse(NeuralAnalysisError):
    """The provider response does not satisfy the application contract."""
