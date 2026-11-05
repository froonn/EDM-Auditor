import { ApiError, apiRequest, apiRequestPage, type Page, type RequestOptions } from "./client";
import type {
  AuditPreview,
  AuditResult,
  AuditSelection,
  DocumentDetail,
  DocumentItem,
  DocumentType,
  LegalAct,
  Report,
  ReportListItem,
  Rule,
} from "./types";

/** The API limit of one page. */
export const MAX_PAGE_SIZE = 100;

export interface PageRequest {
  limit: number;
  offset: number;
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
  },

  documentTypes: {
    list: (signal?: AbortSignal) => apiRequest<DocumentType[]>("/api/document-types", { signal }),
  },

  legalActs: {
    all: (signal?: AbortSignal) => fetchAll<LegalAct>("/api/legal-acts", { signal }),
  },

  rules: {
    allActive: (signal?: AbortSignal) => fetchAll<Rule>("/api/rules", { query: { is_active: true }, signal }),
    all: (signal?: AbortSignal) => fetchAll<Rule>("/api/rules", { signal }),
  },
};
