"""Document type catalog and deterministic document classification."""

from .classifier import classify_document
from .models import (
    ClassificationCandidate,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    DocumentTypeProfile,
)

__all__ = [
    "ClassificationCandidate",
    "ClassificationResult",
    "ClassificationSource",
    "ClassificationStatus",
    "DocumentTypeProfile",
    "classify_document",
]
