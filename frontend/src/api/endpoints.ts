import { ApiError, apiDownload, apiRequest, apiRequestPage, type Page, type RequestOptions } from "./client";
import type {
  ApplicabilityScope,
  AuditPreview,
  AuditResult,
  AuditSelection,
  DocumentDetail,
  DocumentItem,
  DocumentType,
  DocumentTypeSuggestion,
  ExportFormat,
  LegalAct,
  LegalActDetail,
  LegalActDiagnostics,
  Report,
  ReportListItem,
  Rule,
  RuleCreate,
  RuleUpdate,
} from "./types";

/** The API limit of one page. */
export const MAX_PAGE_SIZE = 100;

export interface PageRequest {
  limit: number;
  offset: number;
}

export interface RuleFilters {
  is_active?: boolean;
  document_type?: string;
  check_type?: string;
  applicability_scope?: ApplicabilityScope;
}

/** Reads every page of a list; meant for small catalogs such as rules and legal acts. */
async function fetchAll<T>(path: string, options: RequestOptions = {}): Promise<T[]> {
  const items: T[] = [];
  for (;;) {
    const page: Page<T> = await apiRequestPage<T>(path, {
      ...options,
      query: { ...options.query, limit: MAX_PAGE_SIZE, offset: items.length },
    });
    items.push(...page.items);
    if (page.items.length === 0 || items.length >= page.total) return items;
  }
}

/** API calls grouped by resource. Comments mark the calls that send requests to a model. */
export const api = {
  health: (signal?: AbortSignal) => apiRequest<{ status: string }>("/health", { signal }),

  documents: {
    list: ({ limit, offset }: PageRequest, signal?: AbortSignal) =>
      apiRequestPage<DocumentItem>("/api/documents", { query: { limit, offset }, signal }),
    get: (id: number, signal?: AbortSignal) => apiRequest<DocumentDetail>(`/api/documents/${id}`, { signal }),
    /** Calls the model to determine the document type. */
    upload: (file: File, title?: string) => {
      const form = new FormData();
      form.append("file", file);
      if (title) form.append("title", title);
      return apiRequest<DocumentItem>("/api/documents/upload", { form });
    },
    remove: (id: number) => apiRequest<void>(`/api/documents/${id}`, { method: "DELETE" }),
    /** Calls the model. */
    classify: (id: number) => apiRequest<DocumentItem>(`/api/documents/${id}/classify`, { method: "POST" }),
    /** An empty list restores the automatic result. */
    setTypes: (id: number, codes: string[]) =>
      apiRequest<DocumentItem>(`/api/documents/${id}/classification`, {
        method: "PATCH",
        json: { confirmed_document_types: codes },
      }),
    /** Calls the embedding model, and the classifier if the type is still missing. */
    preview: (id: number, selection: AuditSelection) =>
      apiRequest<AuditPreview>(`/api/documents/${id}/audit/preview`, { method: "POST", json: selection }),
    /** Calls the models; never repeat it automatically. */
    audit: (id: number, selection?: AuditSelection) =>
      apiRequest<AuditResult>(`/api/documents/${id}/audit`, { method: "POST", json: selection ?? {} }),
    /** The newest report, or `null` before the first audit. */
    report: async (id: number, reportId?: number, signal?: AbortSignal): Promise<Report | null> => {
      try {
        return await apiRequest<Report>(`/api/documents/${id}/report`, {
          query: { report_id: reportId },
          signal,
        });
      } catch (error) {
        if (error instanceof ApiError && error.code === "report_not_found" && reportId === undefined) {
          return null;
        }
        throw error;
      }
    },
  },

  reports: {
    listForDocument: (documentId: number, signal?: AbortSignal) =>
      apiRequestPage<ReportListItem>("/api/reports", {
        query: { document_id: documentId, limit: MAX_PAGE_SIZE },
        signal,
      }),
    /** Dates in the file are shown in the given IANA time zone, as on the screen. */
    export: (reportId: number, format: ExportFormat, timeZone: string) =>
      apiDownload(`/api/reports/${reportId}/export`, `audit-report-${reportId}.${format}`, {
        query: { format, timezone: timeZone },
      }),
  },

  documentTypes: {
    list: (signal?: AbortSignal) => apiRequest<DocumentType[]>("/api/document-types", { signal }),
    listAll: (signal?: AbortSignal) =>
      apiRequest<DocumentType[]>("/api/document-types", { query: { include_inactive: true }, signal }),
    /** Also brings back a deactivated type with the same code. */
    create: (type: { code: string; name: string; description: string }) =>
      apiRequest<DocumentType>("/api/document-types", { json: type }),
    update: (code: string, changes: { name?: string; description?: string }) =>
      apiRequest<DocumentType>(`/api/document-types/${encodeURIComponent(code)}`, { method: "PATCH", json: changes }),
    deactivate: (code: string) =>
      apiRequest<void>(`/api/document-types/${encodeURIComponent(code)}`, { method: "DELETE" }),
    suggestions: (signal?: AbortSignal) =>
      apiRequest<DocumentTypeSuggestion[]>("/api/document-type-suggestions", { signal }),
    acceptSuggestion: (id: number, type: { code: string; name?: string; description?: string }) =>
      apiRequest<DocumentType>(`/api/document-type-suggestions/${id}/accept`, { json: type }),
    dismissSuggestion: (id: number) =>
      apiRequest<void>(`/api/document-type-suggestions/${id}/dismiss`, { method: "POST" }),
  },

  legalActs: {
    all: (signal?: AbortSignal) => fetchAll<LegalAct>("/api/legal-acts", { signal }),
    list: ({ limit, offset, search }: PageRequest & { search?: string }, signal?: AbortSignal) =>
      apiRequestPage<LegalAct>("/api/legal-acts", { query: { limit, offset, search: search || undefined }, signal }),
    get: (id: number, signal?: AbortSignal) => apiRequest<LegalActDetail>(`/api/legal-acts/${id}`, { signal }),
    diagnostics: (id: number, signal?: AbortSignal) =>
      apiRequest<LegalActDiagnostics>(`/api/legal-acts/${id}/diagnostics`, { signal }),
    /** Calls the model for every chunk of the act; never repeat it automatically. */
    upload: (file: File, fields: { code: string; title: string; number?: string; source_url?: string; document_types: string[] }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("code", fields.code);
      form.append("title", fields.title);
      if (fields.number) form.append("number", fields.number);
      if (fields.source_url) form.append("source_url", fields.source_url);
      if (fields.document_types.length > 0) form.append("document_types", fields.document_types.join(","));
      return apiRequest<LegalAct>("/api/legal-acts/upload", { form });
    },
    update: (id: number, changes: Partial<Pick<LegalActDetail, "code" | "title" | "number" | "source_url" | "article_text" | "document_types">>) =>
      apiRequest<LegalAct>(`/api/legal-acts/${id}`, { method: "PATCH", json: changes }),
    /** Calls the model again and replaces the generated rules. */
    reprocess: (id: number) => apiRequest<LegalAct>(`/api/legal-acts/${id}/reprocess`, { method: "POST" }),
    remove: (id: number) => apiRequest<void>(`/api/legal-acts/${id}`, { method: "DELETE" }),
  },

  rules: {
    allActive: (signal?: AbortSignal) => fetchAll<Rule>("/api/rules", { query: { is_active: true }, signal }),
    all: (signal?: AbortSignal) => fetchAll<Rule>("/api/rules", { signal }),
    list: (request: PageRequest & RuleFilters, signal?: AbortSignal) =>
      apiRequestPage<Rule>("/api/rules", { query: { ...request }, signal }),
    create: (rule: RuleCreate) => apiRequest<Rule>("/api/rules", { json: rule }),
    update: (id: number, changes: RuleUpdate) => apiRequest<Rule>(`/api/rules/${id}`, { method: "PATCH", json: changes }),
    setApplicability: (id: number, scope: ApplicabilityScope, documentTypes: string[]) =>
      apiRequest<Rule>(`/api/rules/${id}/applicability`, {
        method: "PATCH",
        json: { applicability_scope: scope, document_types: documentTypes },
      }),
    remove: (id: number) => apiRequest<void>(`/api/rules/${id}`, { method: "DELETE" }),
  },
};
