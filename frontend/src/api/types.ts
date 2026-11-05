import type { components } from "./schema";

/** Response and request models generated from the backend OpenAPI schema. */
export type Schemas = components["schemas"];

export type DocumentItem = Schemas["DocumentResponse"];
export type DocumentDetail = Schemas["DocumentDetailResponse"];
export type DocumentType = Schemas["DocumentTypeResponse"];
export type LegalAct = Schemas["LegalActResponse"];
export type Rule = Schemas["RuleResponse"];
export type Report = Schemas["ReportResponse"];
export type ReportListItem = Schemas["ReportListResponse"];
export type Finding = Schemas["FindingResponse"];
export type NeuralAnalysis = Schemas["NeuralAnalysisResponse"];
export type AuditPreview = Schemas["AuditPreviewResponse"];
export type AuditResult = Schemas["AuditRequestResponse"];

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
