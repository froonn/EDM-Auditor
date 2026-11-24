"""Allowed values persisted by the database schema."""

from enum import StrEnum


class GroupKind(StrEnum):
    SYSTEM = "system"
    CUSTOM = "custom"
    PERSONAL = "personal"


class ResolutionDecision(StrEnum):
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    AUDITED = "audited"
    ERROR = "error"


class AuditSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
