import type { components } from "./schema";

/** Response and request models generated from the backend OpenAPI schema. */
export type Schemas = components["schemas"];

export type DocumentItem = Schemas["DocumentResponse"];
export type DocumentDetail = Schemas["DocumentDetailResponse"];
export type DocumentStatement = Schemas["DocumentStatementResponse"];
export type DocumentType = Schemas["DocumentTypeResponse"];
export type LegalAct = Schemas["LegalActResponse"];
export type Rule = Schemas["RuleResponse"];
export type Report = Schemas["ReportResponse"];
export type ReportListItem = Schemas["ReportListResponse"];
export type Finding = Schemas["FindingResponse"];
export type NeuralAnalysis = Schemas["NeuralAnalysisResponse"];
export type AuditPreview = Schemas["AuditPreviewResponse"];
export type AuditResult = Schemas["AuditRequestResponse"];
export type LegalActDetail = Schemas["LegalActDetailResponse"];
export type LegalActDiagnostics = Schemas["LegalActDiagnosticsResponse"];
export type DocumentTypeSuggestion = Schemas["DocumentTypeSuggestionResponse"];
export type RuleCreate = Schemas["RuleCreate"];
export type RuleUpdate = Schemas["RuleUpdate"];
export type AuthUser = Schemas["AuthUserResponse"];
export type GroupSummary = Schemas["GroupSummaryResponse"];
export type UserItem = Schemas["UserResponse"];
export type UserCreate = Schemas["UserCreate"];
export type UserUpdate = Schemas["UserUpdate"];
export type GroupItem = Schemas["GroupResponse"];
export type GroupMember = Schemas["GroupMemberSummary"];
export type GroupCreate = Schemas["GroupCreate"];
export type GroupUpdate = Schemas["GroupUpdate"];
export type PermissionInfo = Schemas["PermissionInfoResponse"];
export type AuthAuditLogItem = Schemas["AuthAuditLogResponse"];
export type Resolution = Schemas["ResolutionResponse"];
export type ResolutionCreate = Schemas["ResolutionCreate"];
export type TransferSuperAdminResponse = Schemas["TransferSuperAdminResponse"];
export type RevokeSessionsResponse = Schemas["RevokeSessionsResponse"];

export type GroupKind = "system" | "custom" | "personal";
export type ResolutionDecision = "approved" | "needs_revision" | "rejected";

export type ApplicabilityScope = "universal" | "typed" | "manual_only" | "unknown";
/** Scopes a person may set; `unknown` only describes an uncertain model answer. */
export const MANUAL_SCOPES: readonly ApplicabilityScope[] = ["universal", "typed", "manual_only"];

/** Check types the audit runs. `semantic` is refused by the API and is never offered. */
export type SelectionMode = "automatic" | "manual" | "combined" | "all";
export const SELECTION_MODES: readonly SelectionMode[] = ["automatic", "manual", "combined", "all"];

/** The request body of an audit or a preview; every field is optional on the server. */
export interface AuditSelection {
  selection_mode: SelectionMode;
  legal_act_ids: number[];
  included_rule_ids: number[];
  excluded_rule_ids: number[];
  confirm_all: boolean;
}

/** Report file formats of `GET /api/reports/{id}/export`; PDF and DOCX are planned for the diploma. */
export type ExportFormat = "html";
export const EXPORT_FORMATS: readonly ExportFormat[] = ["html"];

export type Severity = "critical" | "high" | "medium" | "low";
/** From the most to the least severe. */
export const SEVERITIES: readonly Severity[] = ["critical", "high", "medium", "low"];

export function isSeverity(value: string): value is Severity {
  return (SEVERITIES as readonly string[]).includes(value);
}

export type DocumentStatus = "uploaded" | "processing" | "audited" | "error";
export type ClassificationStatus = "pending" | "classified" | "needs_review" | "unknown";
export type LegalActStatus =
  | "uploaded"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "needs_reprocessing";
