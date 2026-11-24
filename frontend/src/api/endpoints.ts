import { ApiError, apiDownload, apiRequest, apiRequestPage, type Page, type RequestOptions } from "./client";
import type {
  ApplicabilityScope,
  AuditPreview,
  AuditResult,
  AuditSelection,
  AuthAuditLogItem,
  AuthUser,
  DocumentDetail,
  DocumentItem,
  DocumentStatement,
  DocumentType,
  DocumentTypeSuggestion,
  ExportFormat,
  GroupCreate,
  GroupItem,
  GroupKind,
  GroupUpdate,
  LegalAct,
  LegalActDetail,
  LegalActDiagnostics,
  PermissionInfo,
  Report,
  ReportListItem,
  Resolution,
  ResolutionCreate,
  RevokeSessionsResponse,
  Rule,
  RuleCreate,
  RuleUpdate,
  TransferSuperAdminResponse,
  UserCreate,
  UserItem,
  UserUpdate,
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
  applicability_scope?: ApplicabilityScope;
  legal_act_id?: number;
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

  auth: {
    me: (signal?: AbortSignal) => apiRequest<AuthUser>("/api/auth/me", { signal }),
    login: (username: string, password: string) =>
      apiRequest<AuthUser>("/api/auth/login", { json: { username, password } }),
    logout: () => apiRequest<void>("/api/auth/logout", { method: "POST" }),
    logoutAll: () => apiRequest<void>("/api/auth/logout-all", { method: "POST" }),
    changePassword: (current_password: string, new_password: string) =>
      apiRequest<AuthUser>("/api/auth/change-password", {
        json: { current_password, new_password },
      }),
    transferSuperAdmin: (current_password: string, target_user_id: number) =>
      apiRequest<TransferSuperAdminResponse>("/api/auth/transfer-super-admin", {
        json: { current_password, target_user_id },
      }),
    auditLog: (
      params: PageRequest & { action?: string; actor_username?: string },
      signal?: AbortSignal,
    ) =>
      apiRequestPage<AuthAuditLogItem>("/api/auth/audit-log", {
        query: {
          limit: params.limit,
          offset: params.offset,
          action: params.action || undefined,
          actor_username: params.actor_username || undefined,
        },
        signal,
      }),
  },

  users: {
    list: (
      params: PageRequest & { search?: string; is_active?: boolean },
      signal?: AbortSignal,
    ) =>
      apiRequestPage<UserItem>("/api/users", {
        query: {
          limit: params.limit,
          offset: params.offset,
          search: params.search || undefined,
          is_active: params.is_active,
        },
        signal,
      }),
    create: (payload: UserCreate) => apiRequest<UserItem>("/api/users", { json: payload }),
    update: (id: number, payload: UserUpdate) =>
      apiRequest<UserItem>(`/api/users/${id}`, { method: "PATCH", json: payload }),
    setGroups: (id: number, custom_group_ids: number[]) =>
      apiRequest<UserItem>(`/api/users/${id}/groups`, {
        method: "PUT",
        json: { custom_group_ids },
      }),
    revokeSessions: (id: number) =>
      apiRequest<RevokeSessionsResponse>(`/api/users/${id}/revoke-sessions`, { method: "POST" }),
  },

  groups: {
    list: (params?: { kind?: GroupKind; search?: string }, signal?: AbortSignal) =>
      apiRequest<GroupItem[]>("/api/groups", {
        query: { kind: params?.kind, search: params?.search || undefined },
        signal,
      }),
    create: (payload: GroupCreate) => apiRequest<GroupItem>("/api/groups", { json: payload }),
    update: (id: number, payload: GroupUpdate) =>
      apiRequest<GroupItem>(`/api/groups/${id}`, { method: "PATCH", json: payload }),
    setPermissions: (id: number, permissions: string[]) =>
      apiRequest<GroupItem>(`/api/groups/${id}/permissions`, {
        method: "PUT",
        json: { permissions },
      }),
    remove: (id: number) => apiRequest<void>(`/api/groups/${id}`, { method: "DELETE" }),
  },

  permissions: {
    list: (signal?: AbortSignal) => apiRequest<PermissionInfo[]>("/api/permissions", { signal }),
  },

  documents: {
    list: ({ limit, offset, status }: PageRequest & { status?: string }, signal?: AbortSignal) =>
      apiRequestPage<DocumentItem>("/api/documents", {
        query: { limit, offset, status: status || undefined },
        signal,
      }),
    get: (id: number, signal?: AbortSignal) => apiRequest<DocumentDetail>(`/api/documents/${id}`, { signal }),
    statements: (id: number, signal?: AbortSignal) =>
      apiRequest<DocumentStatement[]>(`/api/documents/${id}/statements`, { signal }),
    /** Calls the model to extract statements from the document. */
    extractStatements: (id: number, force = false) =>
      apiRequest<DocumentStatement[]>(`/api/documents/${id}/statements/extract`, {
        method: "POST",
        query: force ? { force: true } : undefined,
      }),
    /** Manually binds or unbinds a statement to an audit rule in the report. */
    linkStatement: (documentId: number, statementId: number, ruleId: number | null, reportId?: number) =>
      apiRequest<Report>(`/api/documents/${documentId}/statements/${statementId}/link`, {
        method: "PATCH",
        json: { rule_id: ruleId, report_id: reportId ?? null },
      }),
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
    resolutions: (reportId: number, signal?: AbortSignal) =>
      apiRequest<Resolution[]>(`/api/reports/${reportId}/resolutions`, { signal }),
    createResolution: (reportId: number, payload: ResolutionCreate) =>
      apiRequest<Resolution>(`/api/reports/${reportId}/resolutions`, { json: payload }),
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
    /** Calls the model again and replaces the generated rules (optionally only failed or one chunk). */
    reprocess: (id: number, options?: { only_failed?: boolean; chunk_id?: string }) =>
      apiRequest<LegalAct>(`/api/legal-acts/${id}/reprocess`, {
        method: "POST",
        query: options ? { only_failed: options.only_failed, chunk_id: options.chunk_id } : undefined,
      }),
    remove: (id: number) => apiRequest<void>(`/api/legal-acts/${id}`, { method: "DELETE" }),
  },

  rules: {
    allActive: (signal?: AbortSignal) => fetchAll<Rule>("/api/rules", { query: { is_active: true }, signal }),
    forLegalAct: (legalActId: number, signal?: AbortSignal) =>
      fetchAll<Rule>("/api/rules", { query: { legal_act_id: legalActId }, signal }),
    get: (id: number, signal?: AbortSignal) => apiRequest<Rule>(`/api/rules/${id}`, { signal }),
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
