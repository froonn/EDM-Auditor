"""Persist the document type catalog, classification results, and type suggestions."""

from collections.abc import Callable, Sequence
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from edm_auditor.database.models import Document, DocumentType, DocumentTypeSuggestion
from edm_auditor.model_providers import DocumentTypeOption

from .catalog import DEFAULT_DOCUMENT_TYPES
from .classifier import DocumentClassifier
from .models import (
    ClassificationCandidate,
    ClassificationModelError,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    TypeSuggestion,
)

logger = logging.getLogger(__name__)


def ensure_default_document_types(session_factory: Callable[[], Session]) -> None:
    """Add missing catalog defaults without reviving deactivated types."""
    with session_factory.begin() as session:
        existing = set(session.scalars(select(DocumentType.code)).all())
        for item in DEFAULT_DOCUMENT_TYPES:
            if item.code not in existing:
                session.add(
                    DocumentType(code=item.code, name=item.name, description=item.description)
                )


def active_document_types(session: Session) -> Sequence[DocumentType]:
    return session.scalars(
        select(DocumentType)
        .where(DocumentType.is_active.is_(True))
        .order_by(DocumentType.code)
    ).all()


def document_type_options(session: Session) -> tuple[DocumentTypeOption, ...]:
    """Describe the active catalog for a model prompt."""
    return tuple(
        DocumentTypeOption(row.code, row.name, row.description)
        for row in active_document_types(session)
    )


def store_classification(
    session: Session, document: Document, result: ClassificationResult
) -> ClassificationResult:
    """Refresh the automatic result; a manual override keeps priority over it."""
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
        automatic = _automatic_result(document)
        if automatic is None:
            _clear_types(document)
            return stored_classification(document)
        _store_types(session, document, automatic)
        return automatic
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
            document.classification_source or ClassificationSource.LLM.value
        ),
    )


def record_type_suggestion(
    session: Session,
    suggestion: TypeSuggestion,
    *,
    document_id: int | None = None,
    legal_act_id: int | None = None,
) -> None:
    """Keep one suggestion per name, so a dismissed type is not proposed again."""
    normalized = " ".join(suggestion.name.casefold().split())
    if not normalized:
        return
    names = session.scalars(select(DocumentType.name)).all()
    if normalized in {" ".join(name.casefold().split()) for name in names}:
        return
    existing = session.scalar(
        select(DocumentTypeSuggestion).where(
            DocumentTypeSuggestion.normalized_name == normalized
        )
    )
    if existing is not None:
        existing.occurrences += 1
        return
    session.add(
        DocumentTypeSuggestion(
            name=suggestion.name[:255],
            normalized_name=normalized[:255],
            reason=suggestion.reason[:1000],
            document_id=document_id,
            legal_act_id=legal_act_id,
        )
    )
    session.flush()


class DocumentClassificationService:
    """Call the model outside database transactions and store what it returned."""

    def __init__(
        self, session_factory: Callable[[], Session], classifier: DocumentClassifier
    ) -> None:
        self._session_factory = session_factory
        self._classifier = classifier

    def classify(self, document_id: int) -> ClassificationResult:
        with self._session_factory() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise LookupError(f"Document {document_id} does not exist")
            text = document.raw_text
            title = document.title
            filename = document.file_path.rsplit("/", 1)[-1]
            options = document_type_options(session)
        try:
            outcome = self._classifier.classify(
                text, title=title, filename=filename, document_types=options
            )
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning("Classification of document %s failed: %s", document_id, exc)
            raise ClassificationModelError("document classification failed") from exc
        with self._session_factory.begin() as session:
            document = session.get(Document, document_id)
            result = store_classification(session, document, outcome.result)
            if outcome.suggestion is not None:
                record_type_suggestion(session, outcome.suggestion, document_id=document_id)
            return result

    def ensure_classified(self, document_id: int) -> None:
        """Classify a document that has no result, for example after a model failure."""
        with self._session_factory() as session:
            document = session.get(Document, document_id)
            if document is None or document.classification_status is not None:
                return
        self.classify(document_id)


def _automatic_result(document: Document) -> ClassificationResult | None:
    if not document.classification_auto:
        return None
    values = json.loads(document.classification_auto)
    known_sources = {item.value for item in ClassificationSource}
    return ClassificationResult(
        ClassificationStatus(values["classification_status"]),
        confirmed_document_types=tuple(values["confirmed_document_types"]),
        candidate_types=tuple(
            ClassificationCandidate(item["code"], item["confidence"])
            for item in values["candidate_types"]
        ),
        confidence=values["confidence"],
        source=ClassificationSource(
            values["source"]
            if values.get("source") in known_sources
            else ClassificationSource.LEGACY.value
        ),
    )


def _clear_types(document: Document) -> None:
    document.confirmed_types = []
    document.classified_type = None
    document.classification_status = None
    document.classification_confidence = None
    document.classification_candidates = None


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
    confirmed = [
        types[code] for code in result.confirmed_document_types if code in types
    ]
    document.confirmed_types = confirmed
    document.classified_type = confirmed[0].code if confirmed else None
    document.classification_status = result.status.value
    document.classification_confidence = result.confidence
    document.classification_candidates = json.dumps(
        [item.as_dict() for item in result.candidate_types],
        ensure_ascii=False,
        sort_keys=True,
    )
    document.classification_source = result.source.value
