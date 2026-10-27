"""Repositories for persistence operations."""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from edm_auditor.document_parser import ParsedDocument

from .enums import AuditSeverity, CheckType, DocumentStatus
from .models import AuditRule, Document, DocumentParagraph, LegalAct


class DocumentRepository:
    """Persist documents and parser output using caller-owned sessions."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create_document(
        self,
        *,
        title: str,
        file_type: str,
        file_path: str | Path,
        user_id: int | None = None,
    ) -> Document:
        with self._session_factory.begin() as session:
            document = Document(
                title=title,
                file_type=file_type,
                file_path=str(file_path),
                user_id=user_id,
                status=DocumentStatus.UPLOADED.value,
            )
            session.add(document)
            session.flush()
            return document

    def save_parsed_document(
        self,
        parsed: ParsedDocument,
        *,
        title: str | None = None,
        file_path: str | Path | None = None,
        user_id: int | None = None,
    ) -> Document:
        with self._session_factory.begin() as session:
            document = Document(
                title=title or Path(parsed.source.filename).stem,
                file_type=parsed.source.format,
                file_path=str(file_path or parsed.source.filename),
                user_id=user_id,
                raw_text=parsed.text,
                status=DocumentStatus.UPLOADED.value,
            )
            document.paragraphs = [
                DocumentParagraph(
                    paragraph_index=paragraph.index,
                    text=paragraph.text,
                    start_char=paragraph.start_char,
                    end_char=paragraph.end_char,
                    page_number=paragraph.page_number,
                )
                for paragraph in parsed.paragraphs
            ]
            session.add(document)
            session.flush()
            return document

    def get_document(self, document_id: int) -> Document | None:
        with self._session_factory() as session:
            statement = (
                select(Document)
                .options(selectinload(Document.paragraphs))
                .where(Document.id == document_id)
            )
            return session.scalar(statement)

    def update_status(self, document_id: int, status: DocumentStatus) -> None:
        with self._session_factory.begin() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise LookupError(f"Document {document_id} does not exist")
            document.status = status.value

    def create_legal_act(
        self,
        *,
        code: str,
        title: str,
        article_text: str,
        number: str | None = None,
        source_url: str | None = None,
    ) -> LegalAct:
        with self._session_factory.begin() as session:
            legal_act = LegalAct(
                code=code,
                title=title,
                number=number,
                article_text=article_text,
                source_url=source_url,
            )
            session.add(legal_act)
            session.flush()
            return legal_act

    def create_rule(
        self,
        *,
        rule_code: str,
        name: str,
        severity: AuditSeverity,
        check_type: CheckType,
        description: str = "",
        document_type: str | None = None,
        parameters_json: str | None = None,
        legal_act_id: int | None = None,
    ) -> AuditRule:
        with self._session_factory.begin() as session:
            rule = AuditRule(
                rule_code=rule_code,
                name=name,
                severity=severity.value,
                check_type=check_type.value,
                description=description,
                document_type=document_type,
                parameters_json=parameters_json,
                legal_act_id=legal_act_id,
            )
            session.add(rule)
            session.flush()
            return rule
