"""Pydantic schemas exposed by the REST API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _kept_value(value: str | None) -> str:
    """Leave a field out to keep it; a required field cannot be cleared."""
    if value is None or not value.strip():
        raise ValueError("value must not be null or blank")
    return value


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class DocumentTypeCandidate(BaseModel):
    code: str
    confidence: float


class DocumentTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str
    is_active: bool


class DocumentTypeCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)


class DocumentTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)

    @field_validator("name", "description")
    @classmethod
    def _required_value_is_kept(cls, value: str | None) -> str:
        return _kept_value(value)


class DocumentTypeSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    reason: str
    status: str
    occurrences: int
    document_id: int | None
    legal_act_id: int | None
    accepted_code: str | None


class DocumentTypeSuggestionAccept(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)


class ClassificationUpdate(BaseModel):
    confirmed_document_types: list[str]


class LatestReportSummary(BaseModel):
    id: int
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    created_at: datetime


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    file_type: str
    status: str
    classified_type: str | None
    classification_status: str = "unknown"
    classification_confidence: float | None = None
    classification_source: str | None = None
    confirmed_document_types: list[str] = Field(default_factory=list)
    candidate_document_types: list["DocumentTypeCandidate"] = Field(default_factory=list)
    automatic_classification: dict[str, Any] | None = None
    needs_configuration: bool = True
    created_at: datetime
    latest_report: LatestReportSummary | None = None


class DocumentStatementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject: str
    statement_text: str
    constraint_json: dict[str, Any] | None = None
    source_quote: str
    start_char: int
    end_char: int
    prompt_version: str = "1"


class StatementLinkRequest(BaseModel):
    rule_id: int | None = None
    report_id: int | None = None


class DocumentDetailResponse(DocumentResponse):
    """Finding offsets in a report refer to this text."""

    text: str
    statements_version: str | None = None
    statements: list[DocumentStatementResponse] = Field(default_factory=list)


class AuditSelectionRequest(BaseModel):
    selection_mode: Literal["automatic", "manual", "combined", "all"] = "automatic"
    legal_act_ids: list[int] = Field(default_factory=list)
    included_rule_ids: list[int] = Field(default_factory=list)
    excluded_rule_ids: list[int] = Field(default_factory=list)
    confirm_all: bool = False


class RuleDecisionResponse(BaseModel):
    rule_id: int
    rule_code: str
    subject: str
    legal_act_id: int | None
    applicability_scope: str
    document_types: list[str]
    selected: bool
    reason: str


class RagRecommendationResponse(BaseModel):
    legal_act_id: int
    rule_id: int | None
    score: float
    threshold: float
    reason: str


class AuditPreviewResponse(BaseModel):
    document_id: int
    status: str
    selection_mode: str
    classification_status: str
    classification_confidence: float | None
    confirmed_document_types: list[str]
    candidate_document_types: list[DocumentTypeCandidate]
    selected_rule_ids: list[int]
    decisions: list[RuleDecisionResponse]
    warnings: list[str]
    rag_recommendations: list[RagRecommendationResponse]


class AuditRequestResponse(BaseModel):
    report_id: int
    document_id: int
    total_findings: int
    status: str


class ReportListResponse(BaseModel):
    id: int
    document_id: int
    document_title: str
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    created_at: datetime
    neural_status: str = "not_requested"
    selection_mode: str | None = None


class FindingResponse(BaseModel):
    id: int
    rule_id: int | None
    legal_act_id: int | None
    severity: str
    description: str
    start_char: int | None
    end_char: int | None
    quote: str | None
    recommendation: str | None
    source_context: dict[str, Any] | None = None
    finding_key: str | None = None
    rule_code: str | None = None
    rule_name: str | None = None
    legal_act_code: str | None = None
    legal_act_title: str | None = None
    norm_quote: str | None = None
    # The statement of the document the finding is about; null when the condition is not stated.
    statement_text: str | None = None
    # structured: compared by code; model: model estimate; missing: not stated in the document.
    evaluation_mode: str | None = None


class NeuralAnalysisResponse(BaseModel):
    finding_key: str
    explanation: str
    recommendation: str
    confidence: float
    legal_basis: list[dict[str, Any]]


class ReportResponse(BaseModel):
    id: int
    document_id: int
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    summary: dict[str, Any]
    created_at: datetime
    findings: list[FindingResponse]
    neural_status: str = "not_requested"
    neural_analyses: list[NeuralAnalysisResponse] = Field(default_factory=list)
    selection: dict[str, Any] | None = None


class RuleCreate(BaseModel):
    rule_code: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=255)
    constraint_text: str = Field(min_length=1)
    constraint_json: dict[str, Any] | None = None
    condition: str = ""
    severity: str
    applicability_scope: str | None = None
    document_types: list[str] = Field(default_factory=list)
    legal_act_id: int | None = None


class RuleUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    constraint_text: str | None = Field(default=None, min_length=1)
    constraint_json: dict[str, Any] | None = None
    condition: str | None = None
    severity: str | None = None
    is_active: bool | None = None

    @field_validator("subject", "severity")
    @classmethod
    def _required_value_is_kept(cls, value: str | None) -> str:
        return _kept_value(value)

    @field_validator("constraint_text", "condition", "is_active")
    @classmethod
    def _value_is_not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("value must not be null")
        return value


class RuleApplicabilityUpdate(BaseModel):
    applicability_scope: str
    document_types: list[str] = Field(default_factory=list)


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_code: str
    subject: str
    constraint_text: str
    constraint_json: dict[str, Any] | None = None
    condition: str = ""
    applicability_scope: str = "unknown"
    document_types: list[str] = Field(default_factory=list)
    applicability_confidence: float | None = None
    applicability_source: str | None = None
    automatic_applicability: dict[str, Any] | None = None
    severity: str
    is_active: bool
    legal_act_id: int | None
    is_generated: bool = False
    source_quote: str | None = None
    source_location: str | None = None
    source_start: int | None = None
    source_end: int | None = None


class LegalActResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    number: str | None
    source_url: str | None
    processing_status: str = "uploaded"
    processing_version: str | None = None
    chunks_total: int = 0
    chunks_processed: int = 0
    rules_accepted: int = 0
    rules_rejected: int = 0
    document_types: list[str] = Field(default_factory=list)

    @field_validator("document_types", mode="before")
    @classmethod
    def _type_codes(cls, value: Any) -> list[str]:
        return [getattr(item, "code", item) for item in value]


class LegalActDetailResponse(LegalActResponse):
    article_text: str


class RuleExtractionDiagnosticResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_id: str
    status: str
    error_code: str | None
    diagnostic_message: str | None
    rules_total: int
    rules_accepted: int
    rules_rejected: int
    processing_version: str | None
    created_at: datetime


class LegalActDiagnosticsResponse(BaseModel):
    legal_act_id: int
    processing_status: str
    chunks_total: int
    chunks_processed: int
    rules_accepted: int
    rules_rejected: int
    diagnostics: list[RuleExtractionDiagnosticResponse]


class LegalActCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    article_text: str
    number: str | None = Field(default=None, max_length=100)
    source_url: str | None = Field(default=None, max_length=1000)
    document_types: list[str] = Field(default_factory=list)

    @field_validator("article_text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("article_text must not be blank")
        return value


class LegalActUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    article_text: str | None = None
    number: str | None = Field(default=None, max_length=100)
    source_url: str | None = Field(default=None, max_length=1000)
    document_types: list[str] | None = None

    @field_validator("code", "title", "article_text")
    @classmethod
    def _required_value_is_kept(cls, value: str | None) -> str:
        return _kept_value(value)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class GroupSummaryResponse(BaseModel):
    id: int
    name: str
    kind: str


class AuthUserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    is_super_admin: bool
    must_change_password: bool
    groups: list[GroupSummaryResponse] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    last_login_at: datetime | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class TransferSuperAdminRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    target_user_id: int


class TransferSuperAdminResponse(BaseModel):
    previous_super_admin_id: int
    previous_super_admin_username: str
    new_super_admin_id: int
    new_super_admin_username: str


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=1024)
    full_name: str = Field(default="", max_length=255)
    custom_group_ids: list[int] = Field(default_factory=list)
    must_change_password: bool = True


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=1024)

    @field_validator("email")
    @classmethod
    def _email_is_kept(cls, value: str | None) -> str:
        return _kept_value(value)


class UserGroupsUpdate(BaseModel):
    custom_group_ids: list[int] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    is_super_admin: bool
    must_change_password: bool
    personal_group_id: int | None = None
    custom_groups: list[GroupSummaryResponse] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class RevokeSessionsResponse(BaseModel):
    revoked_count: int


class PermissionInfoResponse(BaseModel):
    code: str
    description: str
    super_admin_only: bool = False


class GroupMemberSummary(BaseModel):
    id: int
    username: str
    full_name: str
    is_active: bool


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=1000)
    permissions: list[str] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _name_is_kept(cls, value: str | None) -> str:
        return _kept_value(value)


class GroupPermissionsUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class GroupResponse(BaseModel):
    id: int
    name: str
    kind: str
    description: str
    owner_user_id: int | None = None
    owner_username: str | None = None
    member_count: int = 0
    members: list[GroupMemberSummary] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AuthAuditLogResponse(BaseModel):
    id: int
    actor_user_id: int | None = None
    actor_username: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    created_at: datetime


class ResolutionCreate(BaseModel):
    decision: Literal["approved", "needs_revision", "rejected"]
    comment: str = Field(default="", max_length=4000)


class ResolutionResponse(BaseModel):
    id: int
    report_id: int
    author_id: int | None = None
    author_name: str
    decision: str
    comment: str
    created_at: datetime
