"""Document classification by a language model against the active type catalog."""

from collections.abc import Sequence
import logging

from edm_auditor.model_providers import DocumentClassificationProvider, DocumentTypeOption

from .models import (
    ClassificationCandidate,
    ClassificationOutcome,
    ClassificationResult,
    ClassificationStatus,
    TypeSuggestion,
)

logger = logging.getLogger(__name__)


def classification_sample(text: str, *, head_chars: int, tail_chars: int) -> str:
    """Keep the heading and the closing part: they identify a document's type."""
    if len(text) <= head_chars + tail_chars:
        return text
    tail = text[-tail_chars:] if tail_chars else ""
    return f"{text[:head_chars]}\n[...]\n{tail}"


class DocumentClassifier:
    """Accept only catalog codes and confirm only confident answers."""

    def __init__(
        self,
        provider: DocumentClassificationProvider,
        *,
        min_confidence: float = 0.7,
        head_chars: int = 4000,
        tail_chars: int = 1000,
    ) -> None:
        self._provider = provider
        self._min_confidence = min_confidence
        self._head_chars = head_chars
        self._tail_chars = tail_chars

    def classify(
        self,
        text: str,
        *,
        title: str = "",
        filename: str = "",
        document_types: Sequence[DocumentTypeOption],
    ) -> ClassificationOutcome:
        if not document_types:
            return ClassificationOutcome(ClassificationResult(ClassificationStatus.UNKNOWN))
        payload = self._provider.classify(
            classification_sample(
                text, head_chars=self._head_chars, tail_chars=self._tail_chars
            ),
            title=title,
            filename=filename,
            document_types=document_types,
        )
        candidates = _candidates(payload, {item.code for item in document_types})
        confirmed = tuple(
            item.code for item in candidates if item.confidence >= self._min_confidence
        )
        best = candidates[0].confidence if candidates else 0.0
        if confirmed:
            status = ClassificationStatus.CLASSIFIED
        elif candidates:
            status = ClassificationStatus.NEEDS_REVIEW
        else:
            status = ClassificationStatus.UNKNOWN
        return ClassificationOutcome(
            ClassificationResult(
                status,
                confirmed_document_types=confirmed,
                candidate_types=candidates,
                confidence=best,
            ),
            None if confirmed else _suggestion(payload),
        )


def _candidates(
    payload: object, known_codes: set[str]
) -> tuple[ClassificationCandidate, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("document_types"), list):
        raise ValueError("classification response must contain a document_types array")
    confidences: dict[str, float] = {}
    for item in payload["document_types"]:
        if not isinstance(item, dict):
            raise ValueError("each classified type must be an object")
        code, confidence = item.get("code"), item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("classification confidence must be numeric")
        if not 0 <= confidence <= 1:
            raise ValueError("classification confidence must be between 0 and 1")
        if code not in known_codes:
            logger.warning("Classification model returned a code outside the catalog")
            continue
        confidences[code] = max(float(confidence), confidences.get(code, 0.0))
    return tuple(
        ClassificationCandidate(code, confidence)
        for code, confidence in sorted(
            confidences.items(), key=lambda entry: (-entry[1], entry[0])
        )
    )


def _suggestion(payload: dict) -> TypeSuggestion | None:
    name = payload.get("suggested_type_name")
    reason = payload.get("suggested_type_reason")
    if not isinstance(name, str) or not name.strip():
        return None
    return TypeSuggestion(name.strip(), reason.strip() if isinstance(reason, str) else "")
