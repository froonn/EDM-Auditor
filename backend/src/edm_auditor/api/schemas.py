"""Pydantic schemas exposed by the REST API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    file_type: str
    status: str
    classified_type: str | None
    created_at: datetime


class AuditRequestResponse(BaseModel):
    report_id: int
    document_id: int
    total_findings: int
    status: str


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


class RuleCreate(BaseModel):
    rule_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    severity: str
    check_type: str
    description: str = ""
    document_type: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    legal_act_id: int | None = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_code: str
    name: str
    document_type: str | None
    severity: str
    description: str
    check_type: str
    parameters: dict[str, Any]
    is_active: bool
    legal_act_id: int | None


class LegalActResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    number: str | None
    source_url: str | None
