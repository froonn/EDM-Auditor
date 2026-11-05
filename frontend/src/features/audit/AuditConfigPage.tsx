import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { ArrowLeft, ListChecks } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router";

import { api } from "@/api/endpoints";
import {
  SELECTION_MODES,
  type AuditPreview,
  type AuditSelection,
  type DocumentDetail,
  type LegalAct,
  type Rule,
  type SelectionMode,
} from "@/api/types";
import { SeverityBadge } from "@/components/badges";
import { ErrorAlert } from "@/components/ErrorAlert";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { queryKeys, useDocument, useDocumentTypes } from "@/features/queries";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { useDocumentId } from "./AuditPage";
import { AuditRunner } from "./AuditRunner";
import { ClassificationPanel } from "./ClassificationPanel";

type RuleChoice = "auto" | "include" | "exclude";

export function AuditConfigPage() {
  const documentId = useDocumentId();
  return documentId === null ? <NotFoundPage /> : <ConfigScreen documentId={documentId} />;
}

function ConfigScreen({ documentId }: { documentId: number }) {
  const { t } = useI18n();
  const location = useLocation();
  const document = useDocument(documentId);
  const required = (location.state as { configurationRequired?: boolean } | null)?.configurationRequired === true;

  if (document.isError) return <ErrorAlert error={document.error} onRetry={() => void document.refetch()} />;
  if (!document.data) return <p role="status">{t("table.loading")}</p>;

  return (
    <div className="max-w-5xl space-y-4">
      <Link
        to={`/documents/${documentId}/audit`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline"
      >
        <ArrowLeft aria-hidden className="size-4" />
        {t("config.back")}
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">{t("config.title")}</h1>
        <p className="text-muted-foreground">{document.data.title}</p>
      </div>
      {required && (
        <p role="alert" className="rounded-lg border border-warning bg-warning-muted p-3 text-sm">
          {t("config.requiredNotice")}
        </p>
      )}
      {/* The key re-reads the confirmed types after another tab or a reclassification changed them. */}
      <ClassificationPanel key={(document.data.confirmed_document_types ?? []).join(",")} document={document.data} />
      <SelectionForm document={document.data} />
    </div>
  );
}

function SelectionForm({ document }: { document: DocumentDetail }) {
  const { t } = useI18n();
  const legalActs = useQuery({ queryKey: queryKeys.legalActs, queryFn: ({ signal }) => api.legalActs.all(signal) });
  const rules = useQuery({ queryKey: queryKeys.activeRules, queryFn: ({ signal }) => api.rules.allActive(signal) });

  const [mode, setMode] = useState<SelectionMode>("automatic");
  const [actIds, setActIds] = useState<ReadonlySet<number>>(() => new Set());
  const [choices, setChoices] = useState<ReadonlyMap<number, RuleChoice>>(() => new Map());
  const [confirmAll, setConfirmAll] = useState(false);

  const selection = useMemo<AuditSelection>(() => {
    const pick = (wanted: RuleChoice) =>
      [...choices].filter(([, choice]) => choice === wanted).map(([id]) => id).sort((a, b) => a - b);
    return {
      selection_mode: mode,
      legal_act_ids: [...actIds].sort((a, b) => a - b),
      included_rule_ids: pick("include"),
      excluded_rule_ids: pick("exclude"),
      confirm_all: mode === "all" && confirmAll,
    };
  }, [mode, actIds, choices, confirmAll]);
  const selectionKey = JSON.stringify(selection);

  const preview = useMutation({
    mutationFn: (request: AuditSelection) => api.documents.preview(document.id, request),
  });
  const [previewKey, setPreviewKey] = useState<string>();
  const runPreview = () => {
    setPreviewKey(selectionKey);
    preview.mutate(selection);
  };
  const stale = preview.data !== undefined && previewKey !== selectionKey;
  const blocked = mode === "all" && !confirmAll;

  const toggleAct = (id: number) =>
    setActIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const choose = (id: number, choice: RuleChoice) =>
    setChoices((current) => {
      const next = new Map(current);
      if (choice === "auto") next.delete(id);
      else next.set(id, choice);
      return next;
    });

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2 rounded-lg border bg-card p-4 text-sm">
        <legend className="px-1 text-base font-semibold">{t("config.mode")}</legend>
        {SELECTION_MODES.map((value) => (
          <label key={value} className="flex items-start gap-2">
            <input
              type="radio"
              name="selection_mode"
              value={value}
              checked={mode === value}
              onChange={() => setMode(value)}
              className="mt-1"
            />
            <span>
              <span className="font-medium">{t(`config.mode.${value}`)}</span>
              <span className="block text-muted-foreground">{t(`config.mode.${value}.hint`)}</span>
            </span>
          </label>
        ))}
        {mode === "all" && (
          <label className="flex items-start gap-2 rounded-md border border-warning bg-warning-muted p-3">
            <input
              type="checkbox"
              checked={confirmAll}
              onChange={(event) => setConfirmAll(event.target.checked)}
              className="mt-1"
            />
            {t("config.allRisk")}
          </label>
        )}
      </fieldset>

      <LegalActsChoice query={legalActs} selected={actIds} onToggle={toggleAct} />
      <RulesChoice query={rules} acts={legalActs.data ?? []} choices={choices} onChoose={choose} />

      <section className="space-y-3 rounded-lg border bg-card p-4 text-sm">
        <div className="flex flex-wrap items-start gap-3">
          <div className="space-y-1">
            <Button variant="outline" onClick={runPreview} disabled={preview.isPending || blocked}>
              <ListChecks aria-hidden />
              {t("config.preview")}
            </Button>
            <p className="max-w-sm text-xs text-muted-foreground">{t("config.previewHint")}</p>
          </div>
          <AuditRunner document={document} selection={selection} label={t("config.run")} disabled={blocked} />
        </div>
        {preview.isPending && <LongOperation label={t("config.previewRunning")} />}
        {preview.isError && <ErrorAlert error={preview.error} onRetry={runPreview} />}
        {preview.data && (
          <PreviewResult preview={preview.data} acts={legalActs.data ?? []} stale={stale} />
        )}
      </section>
    </div>
  );
}

function LegalActsChoice({
  query,
  selected,
  onToggle,
}: {
  query: UseQueryResult<LegalAct[]>;
  selected: ReadonlySet<number>;
  onToggle: (id: number) => void;
}) {
  const { t } = useI18n();
  return (
    <fieldset className="space-y-2 rounded-lg border bg-card p-4 text-sm">
      <legend className="px-1 text-base font-semibold">{t("config.legalActs")}</legend>
      <p className="text-muted-foreground">{t("config.legalActs.hint")}</p>
      {query.isError && <ErrorAlert error={query.error} onRetry={() => void query.refetch()} />}
      {query.isPending && <p>{t("table.loading")}</p>}
      {query.data?.length === 0 && <p className="text-muted-foreground">{t("config.legalActs.empty")}</p>}
      {query.data?.map((act) => (
        <label key={act.id} className="flex items-center gap-2">
          <input type="checkbox" checked={selected.has(act.id)} onChange={() => onToggle(act.id)} />
          <span>
            {act.title} <span className="text-muted-foreground">({act.code})</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function RulesChoice({
  query,
  acts,
  choices,
  onChoose,
}: {
  query: UseQueryResult<Rule[]>;
  acts: LegalAct[];
  choices: ReadonlyMap<number, RuleChoice>;
  onChoose: (id: number, choice: RuleChoice) => void;
}) {
  const { t, tOptional } = useI18n();
  const { typeName } = useDocumentTypes();
  const actCodes = new Map(acts.map((act) => [act.id, act.code]));
  const options: RuleChoice[] = ["auto", "include", "exclude"];
  return (
    <section className="space-y-2 rounded-lg border bg-card p-4 text-sm">
      <h2 className="text-base font-semibold">{t("config.rules")}</h2>
      <p className="text-muted-foreground">{t("config.rules.hint")}</p>
      {query.isError && <ErrorAlert error={query.error} onRetry={() => void query.refetch()} />}
      {query.isPending && <p>{t("table.loading")}</p>}
      {query.data?.length === 0 && <p className="text-muted-foreground">{t("config.rules.empty")}</p>}
      {query.data && query.data.length > 0 && (
        <table className="w-full">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="w-32 py-1 font-medium">{t("config.column.severity")}</th>
              <th className="py-1 font-medium">{t("config.column.rule")}</th>
              <th className="py-1 font-medium">{t("config.column.act")}</th>
              <th className="py-1 font-medium">{t("config.column.scope")}</th>
              <th className="py-1 font-medium">{t("config.column.choice")}</th>
            </tr>
          </thead>
          <tbody>
            {query.data.map((rule) => (
              <tr key={rule.id} className="border-t align-top">
                <td className="py-2 pr-3">
                  <SeverityBadge severity={rule.severity} />
                </td>
                <td className="py-2 pr-3">
                  <p className="font-medium">{rule.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">{rule.rule_code}</p>
                </td>
                <td className="py-2 pr-3">{rule.legal_act_id ? (actCodes.get(rule.legal_act_id) ?? "—") : "—"}</td>
                <td className="py-2 pr-3">
                  {tOptional(`scope.${rule.applicability_scope}`) ?? rule.applicability_scope}
                  {(rule.document_types ?? []).length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      {(rule.document_types ?? []).map(typeName).join(", ")}
                    </p>
                  )}
                </td>
                <td className="py-2">
                  <select
                    aria-label={`${t("config.column.choice")}: ${rule.name}`}
                    value={choices.get(rule.id) ?? "auto"}
                    onChange={(event) => onChoose(rule.id, event.target.value as RuleChoice)}
                    className="h-8 rounded-md border bg-card px-2"
                  >
                    {options.map((option) => (
                      <option key={option} value={option}>
                        {t(`config.rule.${option}`)}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function PreviewResult({ preview, acts, stale }: { preview: AuditPreview; acts: LegalAct[]; stale: boolean }) {
  const { t, tOptional, formatNumber } = useI18n();
  const actTitles = new Map(acts.map((act) => [act.id, `${act.title} (${act.code})`]));
  const ready = preview.status === "ready";
  return (
    <div className={cn("space-y-3", stale && "opacity-60")}>
      <h3 className="font-semibold">{t("config.result")}</h3>
      {stale && <p className="text-warning">{t("config.previewStale")}</p>}
      <p className={ready ? "text-success" : "text-warning"}>
        {tOptional(`resolution.${preview.status}`) ?? preview.status}{" "}
        {t("config.selected", { count: preview.selected_rule_ids.length })}
      </p>
      {preview.warnings.length > 0 && (
        <ul className="list-inside list-disc text-warning">
          {preview.warnings.map((warning) => (
            <li key={warning}>{tOptional(`warning.${warning}`) ?? warning}</li>
          ))}
        </ul>
      )}
      <ul className="space-y-1">
        {preview.decisions.map((decision) => (
          <li key={decision.rule_id} className="flex gap-2">
            <span className={cn("w-28 shrink-0", decision.selected ? "text-success" : "text-muted-foreground")}>
              {decision.selected ? t("config.ruleSelected") : t("config.ruleSkipped")}
            </span>
            <span>
              {decision.name} <span className="font-mono text-xs text-muted-foreground">{decision.rule_code}</span>
              <span className="text-muted-foreground"> — {tOptional(`reason.${decision.reason}`) ?? decision.reason}</span>
            </span>
          </li>
        ))}
      </ul>
      {preview.rag_recommendations.length > 0 && (
        <div className="space-y-1">
          <h4 className="font-medium">{t("config.ragTitle")}</h4>
          <p className="text-muted-foreground">{t("config.ragHint")}</p>
          <ul className="list-inside list-disc">
            {preview.rag_recommendations.map((item, index) => (
              <li key={index}>
                {actTitles.get(item.legal_act_id) ?? `#${item.legal_act_id}`} —{" "}
                {t("config.ragScore", {
                  score: formatNumber(item.score, { style: "percent", maximumFractionDigits: 0 }),
                })}
                , {tOptional(`reason.${item.reason}`) ?? item.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
