import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/endpoints";
import type { DocumentItem } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { Can } from "@/auth/Can";
import { SeverityBadge, StatusBadge } from "@/components/badges";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { FormField, Select } from "@/components/ui/form";
import { ResolutionBadge } from "@/features/audit/ResolutionsPanel";
import { queryKeys, useDocumentTypes } from "@/features/queries";
import { useI18n } from "@/i18n";

import { UploadDocument } from "./UploadDocument";

const PAGE_SIZE = 20;

export function DocumentsPage() {
  const { t, formatDateTime } = useI18n();
  const { can, session } = useAuth();
  const { typeName } = useDocumentTypes();
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [deleting, setDeleting] = useState<DocumentItem | null>(null);

  const canReadAll = can("documents.read_all");
  const canAudit = can("audit.run");
  const page = { limit: PAGE_SIZE, offset, status: statusFilter || undefined };
  const documents = useQuery({
    queryKey: queryKeys.documents(page),
    queryFn: ({ signal }) => api.documents.list(page, signal),
    placeholderData: keepPreviousData,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.documents.remove(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments }),
  });

  // Deleting the last document of a page leaves it empty: step back to the previous page.
  const empty = documents.data?.items.length === 0;
  useEffect(() => {
    if (empty && offset > 0) setOffset((current) => Math.max(0, current - PAGE_SIZE));
  }, [empty, offset]);

  const canDeleteDocument = (doc: DocumentItem) => {
    if (can("documents.delete_any")) return true;
    if (!can("documents.delete_own")) return false;
    if (!session.user || doc.owner_id === undefined) return true;
    return doc.owner_id === session.user.id;
  };

  const columns: Column<DocumentItem>[] = [
    {
      key: "title",
      header: t("documents.column.title"),
      cell: (document) => (
        <div>
          <Link to={`/documents/${document.id}/audit`} className="font-medium text-primary hover:underline">
            {document.title}
          </Link>
          <p className="text-xs text-muted-foreground uppercase">{document.file_type}</p>
        </div>
      ),
    },
    ...(canReadAll
      ? [
          {
            key: "owner",
            header: t("documents.column.owner"),
            cell: (document: DocumentItem) =>
              document.owner_name ?? <span className="text-muted-foreground">{t("documents.ownerUnassigned")}</span>,
          } satisfies Column<DocumentItem>,
        ]
      : []),
    {
      key: "type",
      header: t("documents.column.type"),
      cell: (document) =>
        document.needs_configuration ? (
          <StatusBadge kind="classification" status={document.classification_status ?? "unknown"} />
        ) : (
          (document.confirmed_document_types ?? []).map(typeName).join(", ")
        ),
    },
    {
      key: "status",
      header: t("documents.column.status"),
      cell: (document) => <StatusBadge kind="document" status={document.status} />,
    },
    {
      key: "report",
      header: t("documents.column.report"),
      cell: (document) => <LatestReport document={document} canAudit={canAudit} />,
    },
    {
      key: "created",
      header: t("documents.column.created"),
      cell: (document) => formatDateTime(document.created_at),
      className: "whitespace-nowrap",
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("documents.column.actions")}</span>,
      className: "w-0 whitespace-nowrap",
      cell: (document) => (
        <div className="flex gap-2">
          <Can permission="audit.run">
            <Button asChild variant="outline" size="sm">
              <Link to={`/documents/${document.id}/configure`}>{t("documents.configure")}</Link>
            </Button>
          </Can>
          {canDeleteDocument(document) && (
            <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setDeleting(document)}>
              {t("documents.delete")}
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("documents.title")}</h1>
        <p className="text-muted-foreground">{t("documents.description")}</p>
      </div>
      <Can permission="documents.upload">
        <UploadDocument />
      </Can>
      {canReadAll && (
        <div className="flex flex-wrap items-end gap-3">
          <FormField label={t("documents.filter.status")} className="w-64">
            <Select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setOffset(0);
              }}
            >
              <option value="">{t("common.all")}</option>
              <option value="uploaded">{t("documents.filter.waitingAudit")}</option>
              <option value="audited">{t("status.document.audited")}</option>
              <option value="processing">{t("status.document.processing")}</option>
              <option value="error">{t("status.document.error")}</option>
            </Select>
          </FormField>
        </div>
      )}
      {remove.isError && <ErrorAlert error={remove.error} />}
      {documents.isError ? (
        <ErrorAlert error={documents.error} onRetry={() => void documents.refetch()} retrying={documents.isFetching} />
      ) : (
        <DataTable
          columns={columns}
          rows={documents.data?.items}
          rowKey={(document) => document.id}
          isLoading={documents.isPending}
          emptyText={t("documents.empty")}
          pagination={
            documents.data && { limit: PAGE_SIZE, offset, total: documents.data.total, onOffsetChange: setOffset }
          }
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("documents.deleteTitle", { title: deleting?.title ?? "" })}
        description={t("documents.deleteDescription")}
        confirmLabel={t("documents.delete")}
        destructive
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </section>
  );
}

function LatestReport({ document, canAudit }: { document: DocumentItem; canAudit: boolean }) {
  const { t, formatDateTime } = useI18n();
  const report = document.latest_report;
  if (!report) {
    if (!canAudit && document.status === "uploaded") {
      return <span className="text-xs text-muted-foreground">{t("documents.waitingAuditor")}</span>;
    }
    return <span className="text-muted-foreground">{t("documents.noReport")}</span>;
  }
  const counts = [
    ["critical", report.critical_count],
    ["high", report.high_count],
    ["medium", report.medium_count],
    ["low", report.low_count],
  ] as const;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        {report.total_findings === 0 ? (
          <span>{t("documents.noFindings")}</span>
        ) : (
          counts
            .filter(([, count]) => count > 0)
            .map(([severity, count]) => (
              <span key={severity} className="inline-flex items-center gap-1">
                <SeverityBadge severity={severity} />
                {count}
              </span>
            ))
        )}
        {report.latest_resolution && <ResolutionBadge decision={report.latest_resolution.decision} />}
      </div>
      <p className="text-xs text-muted-foreground">{formatDateTime(report.created_at)}</p>
    </div>
  );
}
