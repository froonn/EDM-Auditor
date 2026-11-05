"""SQLAlchemy models for the EDM-Auditor storage schema."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import DocumentStatus, UserRole


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all storage models."""


document_confirmed_types = Table(
    "document_confirmed_types",
    Base.metadata,
    Column(
        "document_id",
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "document_type_code",
        ForeignKey("document_types.code", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


rule_document_types = Table(
    "rule_document_types",
    Base.metadata,
    Column(
        "rule_id",
        ForeignKey("audit_rules.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "document_type_code",
        ForeignKey("document_types.code", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


legal_act_document_types = Table(
    "legal_act_document_types",
    Base.metadata,
    Column(
        "legal_act_id",
        ForeignKey("legal_acts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "document_type_code",
        ForeignKey("document_types.code", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class DocumentType(Base):
    """Catalog entry; ``unknown`` is a classification state and never a row here."""

    __tablename__ = "document_types"

    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    __table_args__ = (
        CheckConstraint("code <> 'unknown'", name="ck_document_types_code"),
    )


class DocumentTypeSuggestion(Base):
    """A catalog addition proposed by a model; it has no effect until a person accepts it."""

    __tablename__ = "document_type_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    occurrences: Mapped[int] = mapped_column(default=1)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    legal_act_id: Mapped[int | None] = mapped_column(
        ForeignKey("legal_acts.id", ondelete="SET NULL"), nullable=True
    )
    accepted_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'dismissed')",
            name="ck_document_type_suggestions_status",
        ),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.HR.value)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    documents: Mapped[list["Document"]] = relationship(back_populates="owner")

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'auditor', 'hr')", name="ck_users_role"),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(1000))
    raw_text: Mapped[str] = mapped_column(Text, default="")
    classified_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_candidates: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_auto: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.UPLOADED.value
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    owner: Mapped[User | None] = relationship(back_populates="documents")
    confirmed_types: Mapped[list[DocumentType]] = relationship(
        secondary=document_confirmed_types, order_by=DocumentType.code
    )
    paragraphs: Mapped[list["DocumentParagraph"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentParagraph.paragraph_index",
        passive_deletes=True,
    )
    reports: Mapped[list["AuditReport"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'audited', 'error')",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "classification_status IS NULL OR "
            "classification_status IN ('classified', 'needs_review', 'unknown')",
            name="ck_documents_classification_status",
        ),
    )


class DocumentParagraph(Base):
    __tablename__ = "document_paragraphs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    paragraph_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int] = mapped_column(Integer)
    end_char: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship(back_populates="paragraphs")

    __table_args__ = (
        UniqueConstraint("document_id", "paragraph_index", name="uq_document_paragraph"),
        CheckConstraint("paragraph_index >= 0", name="ck_paragraph_index"),
        CheckConstraint("start_char >= 0 AND end_char >= start_char", name="ck_range"),
    )


class LegalAct(Base):
    __tablename__ = "legal_acts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    article_text: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="uploaded")
    processing_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    chunks_processed: Mapped[int] = mapped_column(Integer, default=0)
    rules_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rules_rejected: Mapped[int] = mapped_column(Integer, default=0)

    document_types: Mapped[list[DocumentType]] = relationship(
        secondary=legal_act_document_types, order_by=DocumentType.code
    )
    rules: Mapped[list["AuditRule"]] = relationship(
        back_populates="legal_act",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings: Mapped[list["AuditFinding"]] = relationship(
        back_populates="legal_act", passive_deletes=True
    )
    extraction_results: Mapped[list["RuleExtractionResult"]] = relationship(
        back_populates="legal_act",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AuditRule(Base):
    __tablename__ = "audit_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    applicability_scope: Mapped[str] = mapped_column(String(20), default="unknown")
    applicability_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    applicability_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    applicability_auto: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    check_type: Mapped[str] = mapped_column(String(20))
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    legal_act_id: Mapped[int | None] = mapped_column(
        ForeignKey("legal_acts.id", ondelete="CASCADE"), nullable=True
    )
    is_generated: Mapped[bool] = mapped_column(default=False)
    deduplication_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    legal_act: Mapped[LegalAct | None] = relationship(back_populates="rules")
    document_types: Mapped[list[DocumentType]] = relationship(
        secondary=rule_document_types, order_by=DocumentType.code
    )
    findings: Mapped[list["AuditFinding"]] = relationship(back_populates="rule")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_rules_severity",
        ),
        CheckConstraint(
            "check_type IN ('keyword', 'regex', 'numeric', 'date', 'duration', 'semantic')",
            name="ck_rules_check_type",
        ),
        CheckConstraint(
            "parameters_json IS NULL OR json_valid(parameters_json)",
            name="ck_rules_parameters_json",
        ),
        CheckConstraint(
            "applicability_scope IN ('universal', 'typed', 'manual_only', 'unknown')",
            name="ck_rules_applicability_scope",
        ),
    )


class RuleExtractionResult(Base):
    __tablename__ = "rule_extraction_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_act_id: Mapped[int] = mapped_column(
        ForeignKey("legal_acts.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    diagnostic_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_total: Mapped[int] = mapped_column(Integer, default=0)
    rules_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rules_rejected: Mapped[int] = mapped_column(Integer, default=0)
    processing_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    legal_act: Mapped[LegalAct] = relationship(back_populates="extraction_results")

    __table_args__ = (
        UniqueConstraint("legal_act_id", "chunk_id", name="uq_extraction_result_chunk"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'failed', 'partial')",
            name="ck_extraction_result_status",
        ),
    )


class AuditReport(Base):
    __tablename__ = "audit_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    total_findings: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    low_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    document: Mapped[Document] = relationship(back_populates="reports")
    findings: Mapped[list["AuditFinding"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True
    )


class AuditFinding(Base):
    __tablename__ = "audit_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("audit_reports.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_rules.id", ondelete="SET NULL"), nullable=True
    )
    legal_act_id: Mapped[int | None] = mapped_column(
        ForeignKey("legal_acts.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Copies: the report must stay readable after its rule or legal act is deleted.
    finding_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rule_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_act_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    legal_act_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    norm_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    report: Mapped[AuditReport] = relationship(back_populates="findings")
    rule: Mapped[AuditRule | None] = relationship(back_populates="findings")
    legal_act: Mapped[LegalAct | None] = relationship(back_populates="findings")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_findings_severity",
        ),
        CheckConstraint(
            "start_char IS NULL OR (start_char >= 0 AND end_char >= start_char)",
            name="ck_finding_range",
        ),
    )
