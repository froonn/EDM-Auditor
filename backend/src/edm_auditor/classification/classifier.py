"""Deterministic document classifier based on explicit catalog signals."""

from collections.abc import Collection, Iterable

from .models import (
    ClassificationCandidate,
    ClassificationResult,
    ClassificationStatus,
    DocumentTypeProfile,
)

HEADING_WEIGHT = 0.5
TITLE_WEIGHT = 0.3
BODY_TERM_WEIGHT = 0.15
BODY_WEIGHT_LIMIT = 0.3
STRUCTURE_WEIGHT = 0.1
ENTITY_WEIGHT = 0.1

CONFIRMED_CONFIDENCE = 0.6
CANDIDATE_CONFIDENCE = 0.25
REQUIRED_MARGIN = 0.2


def classify_document(
    text: str,
    profiles: Iterable[DocumentTypeProfile],
    *,
    title: str = "",
    filename: str = "",
    entity_kinds: Collection[str] = (),
) -> ClassificationResult:
    """Score catalog types using the heading, file name, terms, structure, and entities."""
    heading, _, body = text.strip().partition("\n")
    heading = heading.casefold()
    body = body.casefold()
    names = f"{title} {filename}".casefold()

    scored: list[tuple[ClassificationCandidate, bool]] = []
    for profile in profiles:
        in_heading = _contains_any(heading, profile.title_terms)
        score = HEADING_WEIGHT if in_heading else 0.0
        if _contains_any(names, profile.title_terms):
            score += TITLE_WEIGHT
        matched_terms = sum(term in body for term in profile.body_terms)
        score += min(matched_terms * BODY_TERM_WEIGHT, BODY_WEIGHT_LIMIT)
        if any(heading.startswith(term) for term in profile.structure_terms):
            score += STRUCTURE_WEIGHT
        if profile.entity_kinds and set(profile.entity_kinds) <= set(entity_kinds):
            score += ENTITY_WEIGHT
        score = round(min(score, 1.0), 2)
        if score >= CANDIDATE_CONFIDENCE:
            scored.append((ClassificationCandidate(profile.code, score), in_heading))

    if not scored:
        return ClassificationResult(ClassificationStatus.UNKNOWN)
    scored.sort(key=lambda item: (-item[0].confidence, item[0].code))
    candidates = tuple(item[0] for item in scored)
    best = candidates[0]

    confirmed = [
        candidate.code
        for candidate, in_heading in scored
        if candidate.confidence >= CONFIRMED_CONFIDENCE and in_heading
    ]
    runner_up = max(
        (item.confidence for item in candidates if item.code not in confirmed),
        default=0.0,
    )
    if confirmed and best.confidence - runner_up >= REQUIRED_MARGIN:
        return ClassificationResult(
            ClassificationStatus.CLASSIFIED,
            confirmed_document_types=tuple(confirmed),
            candidate_types=candidates,
            confidence=best.confidence,
        )
    return ClassificationResult(
        ClassificationStatus.NEEDS_REVIEW,
        candidate_types=candidates,
        confidence=best.confidence,
    )


def _contains_any(value: str, terms: Iterable[str]) -> bool:
    return any(term in value for term in terms)
