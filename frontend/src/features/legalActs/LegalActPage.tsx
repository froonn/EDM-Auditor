import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/endpoints";
import type { LegalActDetail } from "@/api/types";
import { SeverityBadge, StatusBadge } from "@/components/badges";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { ErrorAlert } from "@/components/ErrorAlert";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel, Textarea } from "@/components/ui/form";
import { editableText } from "@/features/audit/textFormat";
import { invalidateCatalog, queryKeys } from "@/features/queries";
import { TypeChecklist } from "@/features/shared/TypeChecklist";
import { useI18n } from "@/i18n";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function LegalActPage() {
  const id = Number(useParams().id);
  return Number.isInteger(id) && id > 0 ? <LegalActScreen id={id} /> : <NotFoundPage />;
}

function LegalActScreen({ id }: { id: number }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const act = useQuery({ queryKey: queryKeys.legalAct(id), queryFn: ({ signal }) => api.legalActs.get(id, signal) });
  const [confirmReprocess, setConfirmReprocess] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const reprocess = useMutation({
    mutationFn: () => api.legalActs.reprocess(id),
    onSettled: () => invalidateCatalog(queryClient),
  });
  const remove = useMutation({
    mutationFn: () => api.legalActs.remove(id),
    onSuccess: () => void navigate("/legal-acts"),
    onSettled: () => invalidateCatalog(queryClient),
  });

  if (act.isError) return <ErrorAlert error={act.error} onRetry={() => void act.refetch()} />;
  if (!act.data) return <p role="status">{t("table.loading")}</p>;
  const data = act.data;
  const busy = reprocess.isPending || remove.isPending;

  return (
    <div className="space-y-4">
      <Link to="/legal-acts" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft aria-hidden className="size-4" />
        {t("legalActs.back")}
      </Link>
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="text-2xl font-semibold break-words">{data.title}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <StatusBadge kind="legalAct" status={data.processing_status ?? "uploaded"} />
            <span>{data.code}</span>
            <span>
              {t("legalActs.rulesCount", { accepted: data.rules_accepted ?? 0, rejected: data.rules_rejected ?? 0 })}
            </span>
          </div>
        </div>
        <Button variant="outline" onClick={() => setConfirmReprocess(true)} disabled={busy}>
          <RefreshCw aria-hidden />
          {t("legalActs.reprocess")}
        </Button>
        <Button variant="destructive" onClick={() => setConfirmDelete(true)} disabled={busy}>
          {t("action.delete")}
        </Button>
      </div>
      {data.processing_status === "needs_reprocessing" && (
        <p role="alert" className="rounded-lg border border-warning bg-warning-muted p-3 text-sm">
          {t("legalActs.stale")}
        </p>
      )}
      {reprocess.isPending && <LongOperation label={t("legalActs.reprocessRunning")} />}
      {reprocess.isError && <ErrorAlert error={reprocess.error} onRetry={() => reprocess.mutate()} />}
      {remove.isError && <ErrorAlert error={remove.error} />}

      {/* After a save the form already holds the saved values, so it is kept; it compares against the new data. */}
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start gap-4">
        <LegalActForm key={data.id} act={data} />
        <div className="space-y-4">
          <Diagnostics id={id} />
          <ActRules id={id} />
        </div>
      </div>

      <ConfirmDialog
        open={confirmReprocess}
        onOpenChange={setConfirmReprocess}
        title={t("legalActs.reprocessTitle")}
        description={t("legalActs.reprocessDescription")}
        confirmLabel={t("legalActs.reprocess")}
        onConfirm={() => reprocess.mutate()}
      />
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("legalActs.deleteTitle", { title: data.title })}
        description={t("legalActs.deleteDescription")}
        confirmLabel={t("action.delete")}
        destructive
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

function LegalActForm({ act }: { act: LegalActDetail }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [code, setCode] = useState(act.code);
  const [title, setTitle] = useState(act.title);
  const [number, setNumber] = useState(act.number ?? "");
  const [sourceUrl, setSourceUrl] = useState(act.source_url ?? "");
  const [types, setTypes] = useState<string[]>(act.document_types ?? []);
  // The stored text separates paragraphs with a blank line; the editor shows one paragraph per line.
  const [editable] = useState(() => editableText(act.article_text));
  const [text, setText] = useState(editable.text);

  // Only changed fields are sent: new document types make the server recompute the applicability
  // of the generated rules, and a new text marks the rules as outdated.
  const changes = (() => {
    const result: Parameters<typeof api.legalActs.update>[1] = {};
    if (code.trim() !== act.code) result.code = code.trim();
    if (title.trim() !== act.title) result.title = title.trim();
    if ((number.trim() || null) !== (act.number ?? null)) result.number = number.trim() || null;
    if ((sourceUrl.trim() || null) !== (act.source_url ?? null)) result.source_url = sourceUrl.trim() || null;
    const before = [...(act.document_types ?? [])].sort().join(",");
    if ([...types].sort().join(",") !== before) result.document_types = types;
    const storedText = editable.toStored(text);
    if (storedText !== act.article_text) result.article_text = storedText;
    return result;
  })();
  const save = useMutation({
    mutationFn: () => api.legalActs.update(act.id, changes),
    onSettled: () => invalidateCatalog(queryClient),
  });
  const valid = code.trim() && title.trim() && text.trim();

  return (
    <Panel title={t("legalActs.edit")}>
      <fieldset disabled={save.isPending} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t("legalActs.field.code")}>
            <Input value={code} onChange={(event) => setCode(event.target.value)} maxLength={100} />
          </FormField>
          <FormField label={t("legalActs.field.title")}>
            <Input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={500} />
          </FormField>
          <FormField label={t("legalActs.field.number")}>
            <Input value={number} onChange={(event) => setNumber(event.target.value)} maxLength={100} />
          </FormField>
          <FormField label={t("legalActs.field.sourceUrl")}>
            <Input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} maxLength={1000} />
          </FormField>
        </div>
        <TypeChecklist label={t("legalActs.field.types")} value={types} onChange={setTypes} />
        <p className="text-xs text-muted-foreground">{t("legalActs.field.typesHint")}</p>
        <FormField label={t("legalActs.field.text")} hint={t("legalActs.field.textHint")}>
          <Textarea value={text} onChange={(event) => setText(event.target.value)} rows={12} className="font-mono text-xs" />
        </FormField>
        <Button onClick={() => save.mutate()} disabled={!valid || Object.keys(changes).length === 0}>
          {t("action.save")}
        </Button>
      </fieldset>
      {save.isSuccess && <p role="status" className="text-sm text-success">{t("action.saved")}</p>}
      {save.isError && <ErrorAlert error={save.error} />}
    </Panel>
  );
}

function Diagnostics({ id }: { id: number }) {
  const { t, tOptional } = useI18n();
  const diagnostics = useQuery({
    queryKey: queryKeys.diagnostics(id),
    queryFn: ({ signal }) => api.legalActs.diagnostics(id, signal),
  });
  return (
    <Panel title={t("legalActs.diagnostics")}>
      {diagnostics.isError ? (
        <ErrorAlert error={diagnostics.error} onRetry={() => void diagnostics.refetch()} />
      ) : (
        <DataTable
          rows={diagnostics.data?.diagnostics}
          rowKey={(item) => item.id}
          isLoading={diagnostics.isPending}
          emptyText={t("legalActs.diagnosticsEmpty")}
          columns={[
            { key: "chunk", header: t("legalActs.column.chunk"), cell: (item) => <span className="font-mono text-xs">{item.chunk_id}</span> },
            {
              key: "result",
              header: t("legalActs.column.result"),
              cell: (item) => (
                <span className={item.status === "failed" ? "text-destructive" : "text-success"}>
                  {tOptional(`status.extraction.${item.status}`) ?? item.status}
                </span>
              ),
            },
            {
              key: "rules",
              header: t("legalActs.column.rules"),
              cell: (item) => t("legalActs.rulesCount", { accepted: item.rules_accepted, rejected: item.rules_rejected }),
            },
            {
              key: "message",
              header: t("legalActs.column.message"),
              cell: (item) =>
                item.error_code || item.diagnostic_message ? (
                  <span className="text-xs break-words">
                    {item.error_code && <span className="font-mono">{item.error_code}</span>} {item.diagnostic_message}
                  </span>
                ) : (
                  t("common.none")
                ),
            },
          ]}
        />
      )}
    </Panel>
  );
}

function ActRules({ id }: { id: number }) {
  const { t } = useI18n();
  const rules = useQuery({
    queryKey: queryKeys.legalActRules(id),
    queryFn: ({ signal }) => api.rules.forLegalAct(id, signal),
  });
  return (
    <Panel title={t("legalActs.rules")}>
      {rules.isError ? (
        <ErrorAlert error={rules.error} onRetry={() => void rules.refetch()} />
      ) : (
        <DataTable
          rows={rules.data}
          rowKey={(rule) => rule.id}
          isLoading={rules.isPending}
          emptyText={t("legalActs.rulesEmpty")}
          columns={[
            { key: "severity", header: t("rules.column.severity"), className: "w-32", cell: (rule) => <SeverityBadge severity={rule.severity} /> },
            {
              key: "rule",
              header: t("rules.column.rule"),
              cell: (rule) => (
                <Link to={`/rules/${rule.id}`} className="text-primary hover:underline">
                  {rule.name}
                </Link>
              ),
            },
            { key: "active", header: t("rules.column.active"), cell: (rule) => t(rule.is_active ? "common.yes" : "common.no") },
          ]}
        />
      )}
    </Panel>
  );
}
