import type { components } from "./schema";

/** Response and request models generated from the backend OpenAPI schema. */
export type Schemas = components["schemas"];

export type Severity = "critical" | "high" | "medium" | "low";
export const SEVERITIES: readonly Severity[] = ["critical", "high", "medium", "low"];

export type DocumentStatus = "uploaded" | "processing" | "audited" | "error";
export type ClassificationStatus = "pending" | "classified" | "needs_review" | "unknown";
export type LegalActStatus =
  | "uploaded"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "needs_reprocessing";
