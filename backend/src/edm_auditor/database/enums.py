"""Allowed values persisted by the database schema."""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    AUDITOR = "auditor"
    HR = "hr"


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


class CheckType(StrEnum):
    KEYWORD = "keyword"
    REGEX = "regex"
    SEMANTIC = "semantic"
