"""SQLAlchemy models for the EDM-Auditor storage schema."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import DocumentStatus, UserRole


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all storage models."""


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
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.UPLOADED.value
    )
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    owner: Mapped[User | None] = relationship(back_populates="documents")
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

    rules: Mapped[list["AuditRule"]] = relationship(back_populates="legal_act")
    findings: Mapped[list["AuditFinding"]] = relationship(back_populates="legal_act")


class AuditRule(Base):
    __tablename__ = "audit_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    check_type: Mapped[str] = mapped_column(String(20))
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    legal_act_id: Mapped[int | None] = mapped_column(
        ForeignKey("legal_acts.id", ondelete="SET NULL"), nullable=True
    )

    legal_act: Mapped[LegalAct | None] = relationship(back_populates="rules")
    findings: Mapped[list["AuditFinding"]] = relationship(back_populates="rule")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_rules_severity",
        ),
        CheckConstraint(
            "check_type IN ('keyword', 'regex', 'numeric', 'semantic')",
            name="ck_rules_check_type",
        ),
        CheckConstraint(
            "parameters_json IS NULL OR json_valid(parameters_json)",
            name="ck_rules_parameters_json",
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
