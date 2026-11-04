"""Persist the document type catalog and classification results."""

from collections.abc import Callable, Sequence
from dataclasses import asdict
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from edm_auditor.audit_engine.extractors import extract_entities
from edm_auditor.database.models import Document, DocumentType

from .catalog import DEFAULT_DOCUMENT_TYPES
from .classifier import classify_document
from .models import (
    ClassificationCandidate,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    DocumentTypeProfile,
)

def ensure_default_document_types(session_factory: Callable[[], Session]) -> None:
    """Add missing catalog defaults without reviving deactivated types."""
    with session_factory.begin() as session:
        existing = set(session.scalars(select(DocumentType.code)).all())
        for item in DEFAULT_DOCUMENT_TYPES:
            if item.profile.code not in existing:
                session.add(
                    DocumentType(
                        code=item.profile.code,
                        name=item.name,
                        description=item.description,
                        classifier_profile=profile_to_json(item.profile),
                    )
                )


def profile_to_json(profile: DocumentTypeProfile) -> str:
    values = asdict(profile)
    del values["code"]
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def profile_from_row(row: DocumentType) -> DocumentTypeProfile:
    values = json.loads(row.classifier_profile or "{}")
    return DocumentTypeProfile(
        code=row.code,
        title_terms=tuple(values.get("title_terms", ())),
        body_terms=tuple(values.get("body_terms", ())),
        structure_terms=tuple(values.get("structure_terms", ())),
        entity_kinds=tuple(values.get("entity_kinds", ())),
    )


def active_document_types(session: Session) -> Sequence[DocumentType]:
    return session.scalars(
        select(DocumentType)
        .where(DocumentType.is_active.is_(True))
        .order_by(DocumentType.code)
    ).all()


def classify_text(
    session: Session, text: str, *, title: str = "", filename: str = ""
) -> ClassificationResult:
    """Classify text against the active catalog without storing the result."""
    return classify_document(
        text,
        [profile_from_row(row) for row in active_document_types(session)],
        title=title,
        filename=filename,
        entity_kinds={item.kind for item in extract_entities(text)},
    )


def classify_and_store(session: Session, document: Document) -> ClassificationResult:
    """Refresh the automatic result; a manual override keeps priority over it."""
    result = classify_text(
        session,
        document.raw_text,
        title=document.title,
        filename=document.file_path.rsplit("/", 1)[-1],
    )
    document.classification_auto = json.dumps(
        result.as_dict(), ensure_ascii=False, sort_keys=True
    )
    if document.classification_source == ClassificationSource.MANUAL.value:
        return stored_classification(document)
    _store_types(session, document, result)
    return result


def override_classification(
    session: Session, document: Document, codes: Sequence[str]
) -> ClassificationResult:
    """Confirm types manually; an empty selection restores the automatic result."""
    if not codes:
        document.classification_source = None
        return classify_and_store(session, document)
    result = ClassificationResult(
        ClassificationStatus.CLASSIFIED,
        confirmed_document_types=tuple(dict.fromkeys(codes)),
        candidate_types=stored_classification(document).candidate_types,
        confidence=1.0,
        source=ClassificationSource.MANUAL,
    )
    _store_types(session, document, result)
    return result


def stored_classification(document: Document) -> ClassificationResult:
    """Read the classification saved on a document; missing data means unknown."""
    candidates = json.loads(document.classification_candidates or "[]")
    return ClassificationResult(
        ClassificationStatus(
            document.classification_status or ClassificationStatus.UNKNOWN.value
        ),
        confirmed_document_types=tuple(sorted(item.code for item in document.confirmed_types)),
        candidate_types=tuple(
            ClassificationCandidate(item["code"], item["confidence"]) for item in candidates
        ),
        confidence=document.classification_confidence or 0.0,
        source=ClassificationSource(
            document.classification_source or ClassificationSource.DETERMINISTIC.value
        ),
    )


def _store_types(
    session: Session, document: Document, result: ClassificationResult
) -> None:
    types = {
        row.code: row
        for row in session.scalars(
            select(DocumentType).where(
                DocumentType.code.in_(result.confirmed_document_types)
            )
        ).all()
    }
    document.confirmed_types = [
        types[code] for code in result.confirmed_document_types
    ]
    document.classified_type = (
        result.confirmed_document_types[0] if result.confirmed_document_types else None
    )
    document.classification_status = result.status.value
    document.classification_confidence = result.confidence
    document.classification_candidates = json.dumps(
        [item.as_dict() for item in result.candidate_types],
        ensure_ascii=False,
        sort_keys=True,
    )
    document.classification_source = result.source.value
