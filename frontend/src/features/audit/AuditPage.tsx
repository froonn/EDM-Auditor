import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CircleCheck, Settings2 } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api } from "@/api/endpoints";
import { SEVERITIES, type DocumentDetail, type Report, type Severity } from "@/api/types";
import { Can } from "@/auth/Can";
import { SeverityBadge, StatusBadge } from "@/components/badges";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { queryKeys, useDocument, useDocumentTypes } from "@/features/queries";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { AuditRunButton, AuditRunStatus, useAuditRunner, type AuditRunner } from "./AuditRunner";
import { DocumentText } from "./DocumentText";
import { FindingsPanel, PassedRules } from "./FindingsPanel";
import { buildSegments } from "./highlight";
import { ReportExtras } from "./ReportExtras";
import { toReportView, type FindingView } from "./reportModel";

export function useDocumentId(): number | null {
  const { id } = useParams();
  const value = Number(id);
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function AuditPage() {
  const documentId = useDocumentId();
  return documentId === null ? <NotFoundPage /> : <AuditScreen documentId={documentId} />;
}

function AuditScreen({ documentId }: { documentId: number }) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const requested = Number(searchParams.get("report"));
  const reportId = Number.isInteger(requested) && requested > 0 ? requested : undefined;

  const document = useDocument(documentId);
  const report = useQuery({
    queryKey: queryKeys.report(documentId, reportId),
    queryFn: ({ signal }) => api.documents.report(documentId, reportId, signal),
  });
  const runner = useAuditRunner({ id: documentId, status: document.data?.status ?? "uploaded" });

  if (document.isError) {
    return <ErrorAlert error={document.error} onRetry={() => void document.refetch()} />;
  }
  if (!document.data) return <p role="status">{t("table.loading")}</p>;

  return (
    <div className="space-y-4">
      <AuditHeader document={document.data} hasReport={Boolean(report.data)} runner={runner} />
      <Can permission="audit.run">
        <AuditRunStatus runner={runner} />
      </Can>
      {document.data.status === "processing" && !runner.audit.isPending && (
        <p role="status" className="rounded-lg border border-primary/30 bg-accent p-3 text-sm">
          {t("audit.processing")}
        </p>
      )}
      {report.isError && <ErrorAlert error={report.error} onRetry={() => void report.refetch()} />}
      {report.isPending && <p role="status">{t("table.loading")}</p>}
      {report.data === null && (
        <div className="rounded-lg border bg-card p-6 text-sm">
          <p className="font-medium">{t("audit.noReport")}</p>
          <p className="text-muted-foreground">{t("audit.noReportHint")}</p>
        </div>
      )}
      {report.data && (
        <ReportView key={report.data.id} document={document.data} report={report.data} selectedReportId={reportId} />
      )}
    </div>
  );
}

function AuditHeader({
  document,
  hasReport,
  runner,
}: {
  document: DocumentDetail;
  hasReport: boolean;
  runner: AuditRunner;
}) {
  const { t } = useI18n();
  const { typeName } = useDocumentTypes();
  return (
    <header className="space-y-3">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft aria-hidden className="size-4" />
        {t("audit.back")}
      </Link>
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="text-2xl font-semibold break-words">{document.title}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <StatusBadge kind="document" status={document.status} />
            {document.needs_configuration ? (
              <StatusBadge kind="classification" status={document.classification_status ?? "unknown"} />
            ) : (
              <span>{(document.confirmed_document_types ?? []).map(typeName).join(", ")}</span>
            )}
          </div>
        </div>
        <Can permission="audit.run">
          <div className="flex shrink-0 items-start gap-2">
            <Button asChild variant="outline">
              <Link to={`/documents/${document.id}/configure`}>
                <Settings2 aria-hidden />
                {t("documents.configure")}
              </Link>
            </Button>
            <AuditRunButton runner={runner} label={hasReport ? t("audit.rerun") : t("audit.run")} />
          </div>
        </Can>
      </div>
    </header>
  );
}

const prefersReducedMotion = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function scrollTo(element: HTMLElement | undefined) {
  element?.scrollIntoView?.({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "center" });
}

function ReportView({
  document,
  report,
  selectedReportId,
}: {
  document: DocumentDetail;
  report: Report;
  selectedReportId: number | undefined;
}) {
  const { t } = useI18n();
  const view = useMemo(() => toReportView(report), [report]);
  const [visible, setVisible] = useState<ReadonlySet<Severity>>(() => new Set(SEVERITIES));
  const [showPassed, setShowPassed] = useState(false);
  // Rule details for the passed rules are read only when the user opens that list.
  const currentRules = useQuery({
    queryKey: queryKeys.allRules,
    queryFn: ({ signal }) => api.rules.all(signal),
    enabled: showPassed,
  });
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<number>>(() => new Set());
  const marks = useRef(new Map<number, HTMLElement>());
  const cards = useRef(new Map<number, HTMLElement>());

  const shown = useMemo(
    () => view.findings.filter((item) => visible.has(item.finding.severity as Severity)),
    [view.findings, visible],
  );
  const segments = useMemo(
    () =>
      buildSegments(
        document.text,
        shown.map(({ finding }) => ({
          id: finding.id,
          severity: finding.severity,
          start: finding.start_char,
          end: finding.end_char,
        })),
      ),
    [document.text, shown],
  );

  const registerMark = useCallback((id: number, element: HTMLElement | null) => {
    if (element) marks.current.set(id, element);
    else marks.current.delete(id);
  }, []);
  const registerCard = useCallback((id: number, element: HTMLElement | null) => {
    if (element) cards.current.set(id, element);
    else cards.current.delete(id);
  }, []);

  // A click in the list scrolls the text to the finding; a click in the text opens its cards.
  const selectFromList = useCallback((item: FindingView) => {
    const id = item.finding.id;
    setSelectedIds((current) => (current.has(id) && current.size === 1 ? new Set() : new Set([id])));
    scrollTo(marks.current.get(id));
  }, []);
  const selectFromText = useCallback((ids: number[]) => {
    setSelectedIds(new Set(ids));
    const first = ids[0];
    if (first !== undefined) window.setTimeout(() => scrollTo(cards.current.get(first)), 0);
  }, []);

  const counts = useMemo(() => {
    const result = new Map<string, number>();
    for (const item of view.findings) result.set(item.finding.severity, (result.get(item.finding.severity) ?? 0) + 1);
    return result;
  }, [view.findings]);

  const toggle = (severity: Severity) =>
    setVisible((current) => {
      const next = new Set(current);
      if (next.has(severity)) next.delete(severity);
      else next.add(severity);
      return next;
    });

  return (
    <div className="space-y-4">
      <ReportPicker documentId={document.id} report={report} selectedReportId={selectedReportId} />
      <section className="space-y-3 rounded-lg border bg-card p-4">
        <h2 className="font-semibold">{t("audit.summary")}</h2>
        <p className="text-sm whitespace-pre-wrap">{view.generalSummary ?? t("audit.noSummary")}</p>
        <div role="group" aria-label={t("audit.filter")} className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">{t("audit.findingsTotal")}:</span>
          {SEVERITIES.map((severity) => (
            <button
              key={severity}
              type="button"
              aria-pressed={visible.has(severity)}
              onClick={() => toggle(severity)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-1.5 py-1 text-sm",
                !visible.has(severity) && "opacity-40",
              )}
            >
              <SeverityBadge severity={severity} />
              {counts.get(severity) ?? 0}
            </button>
          ))}
          <span aria-hidden className="mx-1 h-5 border-l" />
          <button
            type="button"
            aria-pressed={showPassed}
            onClick={() => setShowPassed((current) => !current)}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-sm",
              !showPassed && "opacity-40",
            )}
          >
            <CircleCheck aria-hidden className="size-4 text-success" />
            {t("audit.passedToggle")} {view.passedRules?.length ?? "—"}
          </button>
        </div>
      </section>

      <div className="grid h-[calc(100vh-14rem)] min-h-[32rem] grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-4">
        <section aria-label={t("audit.document")} className="overflow-y-auto rounded-lg border bg-card p-6">
          <DocumentText
            segments={segments}
            selectedIds={selectedIds}
            onSelect={selectFromText}
            registerMark={registerMark}
          />
        </section>
        <section aria-label={t("audit.findingsPanel")} className="overflow-y-auto rounded-lg border bg-muted p-3">
          {view.findings.length === 0 ? (
            <p className="p-3 text-sm">{t("audit.noFindings")}</p>
          ) : shown.length === 0 ? (
            <p className="p-3 text-sm text-muted-foreground">{t("audit.filteredOut")}</p>
          ) : (
            <FindingsPanel
              findings={shown}
              selectedIds={selectedIds}
              onSelect={selectFromList}
              registerCard={registerCard}
            />
          )}
          {showPassed && <PassedRules rules={view.passedRules} current={currentRules} />}
        </section>
      </div>

      <ReportExtras view={view} />
      <p className="text-xs text-muted-foreground">{t("audit.disclaimer")}</p>
    </div>
  );
}

function ReportPicker({
  documentId,
  report,
  selectedReportId,
}: {
  documentId: number;
  report: Report;
  selectedReportId: number | undefined;
}) {
  const { t, formatDateTime } = useI18n();
  const [, setSearchParams] = useSearchParams();
  const history = useQuery({
    queryKey: queryKeys.reportHistory(documentId),
    queryFn: ({ signal }) => api.reports.listForDocument(documentId, signal),
  });
  const items = history.data?.items ?? [];
  const latestId = items[0]?.id;
  const isOlder = selectedReportId !== undefined && latestId !== undefined && report.id !== latestId;

  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <label className="flex items-center gap-2">
        {t("audit.report")}
        <select
          value={report.id}
          onChange={(event) => setSearchParams({ report: event.target.value })}
          disabled={items.length < 2}
          className="h-9 rounded-md border bg-card px-2"
        >
          {items.length === 0 && <option value={report.id}>{formatDateTime(report.created_at)}</option>}
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {t(item.id === latestId ? "audit.reportOptionLatest" : "audit.reportOption", {
                date: formatDateTime(item.created_at),
                count: item.total_findings,
              })}
            </option>
          ))}
        </select>
      </label>
      {isOlder && (
        <span className="flex items-center gap-2 text-muted-foreground">
          {t("audit.olderReport")}
          <Button variant="outline" size="sm" onClick={() => setSearchParams({})}>
            {t("audit.openLatest")}
          </Button>
        </span>
      )}
    </div>
  );
}
