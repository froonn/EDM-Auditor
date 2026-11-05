import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { api, type PageRequest } from "@/api/endpoints";
import type { AuditSelection, DocumentDetail } from "@/api/types";

export const queryKeys = {
  documents: (page: PageRequest) => ["documents", page] as const,
  allDocuments: ["documents"] as const,
  document: (id: number) => ["document", id] as const,
  report: (documentId: number, reportId: number | undefined) => ["report", documentId, reportId ?? "latest"] as const,
  documentReports: (documentId: number) => ["report", documentId] as const,
  reportHistory: (documentId: number) => ["reports", documentId] as const,
  documentTypes: ["documentTypes"] as const,
  legalActs: ["legalActs"] as const,
  activeRules: ["rules", "active"] as const,
  allRules: ["rules", "all"] as const,
};

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

export function useDocumentTypes() {
  const query = useQuery({
    queryKey: queryKeys.documentTypes,
    queryFn: ({ signal }) => api.documentTypes.list(signal),
    staleTime: 60_000,
  });
  const names = useMemo(() => new Map((query.data ?? []).map((item) => [item.code, item.name])), [query.data]);
  return { ...query, typeName: (code: string) => names.get(code) ?? code };
}

/** Starts an audit. It calls the models, so it is never retried automatically. */
export function useRunAudit(document: Pick<DocumentDetail, "id">) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (selection: AuditSelection | undefined) => api.documents.audit(document.id, selection),
    onSettled: () => invalidateDocument(queryClient, document.id),
  });
}
