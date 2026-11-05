"""Document type catalog and model-based document classification."""

from .classifier import DocumentClassifier, classification_sample
from .models import (
    ClassificationCandidate,
    ClassificationModelError,
    ClassificationOutcome,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    TypeSuggestion,
)

__all__ = [
    "ClassificationCandidate",
    "ClassificationModelError",
    "ClassificationOutcome",
    "ClassificationResult",
    "ClassificationSource",
    "ClassificationStatus",
    "DocumentClassifier",
    "TypeSuggestion",
    "classification_sample",
]
