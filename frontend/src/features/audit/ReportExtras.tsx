import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "@/api/endpoints";
import type { DocumentStatement, Report } from "@/api/types";
import { ErrorAlert } from "@/components/ErrorAlert";
import { queryKeys } from "@/features/queries";
import { useI18n } from "@/i18n";

import type { MatchedPair, ReportView } from "./reportModel";
import { asOneLine } from "./textFormat";

function formatStatementConstraint(constraint: Record<string, unknown> | null | undefined): string | null {
  if (!constraint || typeof constraint !== "object") return null;
  const kind = constraint.kind;
  if (kind === "value" && constraint.value !== undefined && constraint.unit !== undefined) {
    return `${String(constraint.value)} ${String(constraint.unit)}`;
  }
  if (kind === "frequency" && constraint.count !== undefined && constraint.period !== undefined) {
    return `${String(constraint.count)} / ${String(constraint.period)}`;
  }
  if (kind === "day_of_month" && constraint.day !== undefined) {
    const offset = Number(constraint.month_offset ?? 0);
    return offset > 0 ? `день ${String(constraint.day)} (+${offset} мес.)` : `день ${String(constraint.day)}`;
  }
  return JSON.stringify(constraint);
}

interface RuleOption {
  id: number;
  code: string;
  subject: string;
}

function selectionRules(report: Report | null | undefined): RuleOption[] {
  const selection = report?.selection as { selection_reasons?: unknown[] } | null | undefined;
  const reasons = Array.isArray(selection?.selection_reasons) ? selection.selection_reasons : [];
  const items: RuleOption[] = [];
  for (const raw of reasons) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    if (typeof item.rule_id === "number") {
      items.push({
        id: item.rule_id,
        code: typeof item.rule_code === "string" ? item.rule_code : String(item.rule_id),
        subject: typeof item.subject === "string" ? item.subject : typeof item.name === "string" ? item.name : String(item.rule_code ?? item.rule_id),
      });
    }
  }
  return items;
}

export function DocumentStatementsSection({
  statements,
  documentId,
  report,
  matchedPairs,
}: {
  statements: DocumentStatement[] | undefined;
  documentId?: number;
  report?: Report | null;
  matchedPairs?: MatchedPair[];
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const list = statements ?? [];
  const fromSelection = selectionRules(report);
  const allRules = useQuery({
    queryKey: queryKeys.activeRules,
    queryFn: ({ signal }) => api.rules.allActive(signal),
    enabled: Boolean(report && list.length > 0 && fromSelection.length === 0),
  });
  const ruleOptions: RuleOption[] =
    fromSelection.length > 0
      ? fromSelection
      : (allRules.data ?? []).map((rule) => ({
          id: rule.id,
          code: rule.rule_code,
          subject: rule.subject ?? rule.rule_code,
        }));
  const ruleById = new Map(ruleOptions.map((item) => [item.id, item]));
  const pairByStatementId = new Map<number, MatchedPair>();
  for (const pair of matchedPairs ?? []) {
    if (pair.statementId !== undefined) pairByStatementId.set(pair.statementId, pair);
  }

  const linkMutation = useMutation({
    mutationFn: ({ statementId, ruleId }: { statementId: number; ruleId: number | null }) =>
      api.documents.linkStatement(documentId!, statementId, ruleId, report?.id),
    onSuccess: (updatedReport) => {
      if (documentId !== undefined) {
        queryClient.setQueryData(queryKeys.report(documentId, report?.id), updatedReport);
        void queryClient.invalidateQueries({ queryKey: queryKeys.document(documentId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.report(documentId, undefined) });
      }
    },
  });

  if (list.length === 0) return null;
  return (
    <Section title={t("extras.statements", { count: list.length })}>
      <p className="text-muted-foreground">{t("extras.statementsHint")}</p>
      {linkMutation.isError && <ErrorAlert error={linkMutation.error} />}
      <ul className="space-y-2">
        {list.map((item) => {
          const structure = formatStatementConstraint(item.constraint_json);
          const pair = pairByStatementId.get(item.id);
          const matchedRule = pair?.ruleId !== undefined ? ruleById.get(pair.ruleId) : undefined;
          const matchedLabel = matchedRule
            ? `${matchedRule.subject} (${matchedRule.code})`
            : pair?.ruleCode;
          return (
            <li key={item.id} className="space-y-1.5 rounded-md bg-muted p-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium">{item.subject}</p>
                {structure && <span className="font-mono text-xs text-muted-foreground">{structure}</span>}
              </div>
              <p>{item.statement_text}</p>
              <p className="text-xs text-muted-foreground italic">«{asOneLine(item.source_quote)}»</p>
              {report && (
                <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs">
                  <span className="text-muted-foreground">
                    {matchedLabel
                      ? t("extras.statementMatchedRule", { rule: matchedLabel })
                      : t("extras.statementUnmatched")}
                  </span>
                  {documentId !== undefined && ruleOptions.length > 0 && (
                    <label className="flex items-center gap-1.5">
                      <span>{t("extras.statementLinkLabel")}:</span>
                      <select
                        aria-label={`${t("extras.statementLinkLabel")}: ${item.subject}`}
                        disabled={linkMutation.isPending}
                        value={pair?.ruleId !== undefined ? String(pair.ruleId) : ""}
                        onChange={(event) => {
                          const raw = event.target.value;
                          linkMutation.mutate({
                            statementId: item.id,
                            ruleId: raw ? Number(raw) : null,
                          });
                        }}
                        className="h-7 rounded border bg-card px-2 text-xs"
                      >
                        <option value="">{t("extras.statementLinkNone")}</option>
                        {ruleOptions.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.subject} ({option.code})
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

/** Secondary report data, collapsed by default. */
export function ReportExtras({
  view,
  statements,
  documentId,
  report,
}: {
  view: ReportView;
  statements?: DocumentStatement[] | undefined;
  documentId?: number;
  report?: Report | null;
}) {
  const { t, tOptional } = useI18n();
  const { selection } = view;
  return (
    <div className="space-y-2">
      <DocumentStatementsSection
        statements={statements}
        documentId={documentId}
        report={report}
        matchedPairs={view.matchedPairs}
      />
      {view.rejected.length > 0 && (
        <Section title={t("extras.rejected", { count: view.rejected.length })}>
          <p className="text-muted-foreground">{t("extras.rejectedHint")}</p>
          <ul className="space-y-2">
            {view.rejected.map((item, index) => (
              <li key={index} className="rounded-md bg-muted p-2">
                {item.quote && <p className="font-medium">«{item.quote}»</p>}
                {item.reason && <p>{item.reason}</p>}
                {item.ruleCode && <p className="font-mono text-xs text-muted-foreground">{item.ruleCode}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {view.diagnostics.length > 0 && (
        <Section title={t("extras.diagnostics", { count: view.diagnostics.length })}>
          <ul className="space-y-1">
            {view.diagnostics.map((item, index) => (
              <li key={index}>
                <span className="font-mono text-xs">{item.ruleCode}</span> {item.message}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <Section title={t("extras.selection")}>
        {selection ? (
          <div className="space-y-1">
            {selection.mode && (
              <p>{t("extras.selectionMode", { mode: tOptional(`config.mode.${selection.mode}`) ?? selection.mode })}</p>
            )}
            <p>{t("extras.appliedRules", { count: selection.appliedRuleCount })}</p>
            {selection.legalActs.length > 0 && (
              <p>
                {t("extras.appliedActs")}:{" "}
                {selection.legalActs.map((act) => [act.title, act.code && `(${act.code})`].filter(Boolean).join(" ")).join("; ")}
              </p>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground">{t("extras.noSelection")}</p>
        )}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="rounded-lg border bg-card text-sm">
      <summary className="cursor-pointer px-4 py-2 font-medium">{title}</summary>
      <div className="space-y-2 border-t px-4 py-3">{children}</div>
    </details>
  );
}
