import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { api, type PageRequest } from "@/api/endpoints";
import { useI18n } from "@/i18n";
import type { AuditSelection, DocumentDetail } from "@/api/types";

export const queryKeys = {
  documents: (page: PageRequest) => ["documents", page] as const,
  allDocuments: ["documents"] as const,
  document: (id: number) => ["document", id] as const,
  report: (documentId: number, reportId: number | undefined) => ["report", documentId, reportId ?? "latest"] as const,
  documentReports: (documentId: number) => ["report", documentId] as const,
  reportHistory: (documentId: number) => ["reports", documentId] as const,
  documentTypes: ["documentTypes"] as const,
  legalActs: ["legalActs", "all"] as const,
  allLegalActs: ["legalActs"] as const,
  legalActPage: (request: object) => ["legalActs", "page", request] as const,
  legalAct: (id: number) => ["legalAct", id] as const,
  anyLegalAct: ["legalAct"] as const,
  diagnostics: (id: number) => ["legalAct", id, "diagnostics"] as const,
  activeRules: ["rules", "active"] as const,
  allRules: ["rules", "all"] as const,
  anyRules: ["rules"] as const,
  rulePage: (request: object) => ["rules", "page", request] as const,
  catalog: ["documentTypes", "catalog"] as const,
  suggestions: ["documentTypeSuggestions"] as const,
};

/**
 * Legal acts, rules and document types depend on each other: an upload adds rules and may add
 * type suggestions, a deleted act removes its rules. Every change refreshes all of them.
 */
export function invalidateCatalog(queryClient: QueryClient) {
  return Promise.all(
    [queryKeys.allLegalActs, queryKeys.anyLegalAct, queryKeys.anyRules, queryKeys.documentTypes, queryKeys.suggestions].map(
      (queryKey) => queryClient.invalidateQueries({ queryKey }),
    ),
  );
}

/** How often a document that is being audited is checked again. */
const PROCESSING_POLL_MS = 5000;

export function invalidateDocument(queryClient: QueryClient, documentId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments }),
    queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.documentReports(documentId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.reportHistory(documentId) }),
  ]);
}

/**
 * The document with its text. While it has the `processing` status, it is checked every few seconds
 * so that a report finished by another tab or before a page reload shows up by itself.
 */
export function useDocument(id: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.document(id),
    queryFn: ({ signal }) => api.documents.get(id, signal),
    refetchInterval: (state) => (state.state.data?.status === "processing" ? PROCESSING_POLL_MS : false),
  });
  const status = query.data?.status;
  const previous = useRef(status);
  useEffect(() => {
    if (previous.current === "processing" && status !== "processing") void invalidateDocument(queryClient, id);
    previous.current = status;
  }, [id, queryClient, status]);
  return query;
}

/**
 * The catalog with deactivated types: rules and acts may still refer to them. `data` holds only the
 * active types, which are the ones a person may choose; `typeName` names deactivated ones as such.
 */
export function useDocumentTypes() {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: queryKeys.catalog,
    queryFn: ({ signal }) => api.documentTypes.listAll(signal),
    staleTime: 60_000,
  });
  const active = useMemo(() => query.data?.filter((item) => item.is_active), [query.data]);
  const byCode = useMemo(() => new Map((query.data ?? []).map((item) => [item.code, item])), [query.data]);
  const typeName = (code: string) => {
    const type = byCode.get(code);
    if (!type) return code;
    return type.is_active ? type.name : `${type.name} (${t("types.inactiveShort")})`;
  };
  const isInactive = (code: string) => byCode.get(code)?.is_active === false;
  return { ...query, data: active, typeName, isInactive };
}

/** Starts an audit. It calls the models, so it is never retried automatically. */
export function useRunAudit(document: Pick<DocumentDetail, "id">) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (selection: AuditSelection | undefined) => api.documents.audit(document.id, selection),
    onSettled: () => invalidateDocument(queryClient, document.id),
  });
}
