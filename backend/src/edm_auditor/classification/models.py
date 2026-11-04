"""Contracts for document types and classification results."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    NEEDS_REVIEW = "needs_review"
    UNKNOWN = "unknown"


class ClassificationSource(StrEnum):
    DETERMINISTIC = "deterministic"
    MANUAL = "manual"
    LEGACY = "legacy"


@dataclass(frozen=True, slots=True)
class DocumentTypeProfile:
    """Signals that identify one catalog type; terms are lowercase word stems."""

    code: str
    title_terms: tuple[str, ...] = ()
    body_terms: tuple[str, ...] = ()
    structure_terms: tuple[str, ...] = ()
    entity_kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassificationCandidate:
    """A possible type; a candidate alone never makes a typed rule applicable."""

    code: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "confidence": self.confidence}


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    status: ClassificationStatus
    confirmed_document_types: tuple[str, ...] = ()
    candidate_types: tuple[ClassificationCandidate, ...] = ()
    confidence: float = 0.0
    source: ClassificationSource = ClassificationSource.DETERMINISTIC

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification_status": self.status.value,
            "confirmed_document_types": list(self.confirmed_document_types),
            "candidate_types": [item.as_dict() for item in self.candidate_types],
            "confidence": self.confidence,
            "source": self.source.value,
        }
