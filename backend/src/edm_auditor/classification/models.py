"""Contracts for document classification results."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    NEEDS_REVIEW = "needs_review"
    UNKNOWN = "unknown"


class ClassificationSource(StrEnum):
    LLM = "llm"
    MANUAL = "manual"
    LEGACY = "legacy"


class ClassificationModelError(RuntimeError):
    """The model did not produce a usable classification."""


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
    source: ClassificationSource = ClassificationSource.LLM

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification_status": self.status.value,
            "confirmed_document_types": list(self.confirmed_document_types),
            "candidate_types": [item.as_dict() for item in self.candidate_types],
            "confidence": self.confidence,
            "source": self.source.value,
        }


@dataclass(frozen=True, slots=True)
class TypeSuggestion:
    """A catalog addition proposed by the model; only a person can accept it."""

    name: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    result: ClassificationResult
    suggestion: TypeSuggestion | None = None
