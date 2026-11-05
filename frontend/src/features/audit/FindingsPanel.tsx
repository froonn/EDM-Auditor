import { useQuery } from "@tanstack/react-query";
import { ChevronDown, CircleCheck } from "lucide-react";
import { useState, type ReactNode } from "react";

import { hasErrorCode } from "@/api/client";
import { api } from "@/api/endpoints";
import { isSeverity } from "@/api/types";
import { SeverityBadge } from "@/components/badges";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Badge } from "@/components/ui/badge";
import { queryKeys } from "@/features/queries";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

import type { FindingView, PassedRule } from "./reportModel";
import { ACCENT_CLASSES } from "./severityStyles";
import { asOneLine, withParagraphBreaks } from "./textFormat";

interface FindingsPanelProps {
  findings: FindingView[];
  selectedIds: ReadonlySet<number>;
  onSelect: (finding: FindingView) => void;
  registerCard: (findingId: number, element: HTMLElement | null) => void;
}

export function FindingsPanel({ findings, selectedIds, onSelect, registerCard }: FindingsPanelProps) {
  return (
    <ul className="space-y-2">
      {findings.map((item) => (
        <li key={item.finding.id} ref={(element) => registerCard(item.finding.id, element)}>
          <FindingItem item={item} expanded={selectedIds.has(item.finding.id)} onSelect={() => onSelect(item)} />
        </li>
      ))}
    </ul>
  );
}

/** A card with a header button that expands its details. */
function Expandable({
  id,
  expanded,
  onToggle,
  accent,
  header,
  children,
}: {
  id: string;
  expanded: boolean;
  onToggle: () => void;
  accent: string | undefined;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    <article className={cn("rounded-lg border border-l-4 bg-card", accent, expanded && "ring-2 ring-ring")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={id}
        className="flex w-full items-start gap-2 p-3 text-left text-sm"
      >
        <div className="min-w-0 flex-1 space-y-1">{header}</div>
        <ChevronDown aria-hidden className={cn("mt-1 size-4 shrink-0 transition-transform", expanded && "rotate-180")} />
      </button>
      {expanded && (
        <div id={id} className="border-t px-3 pb-3">
          {children}
        </div>
      )}
    </article>
  );
}

function FindingItem({ item, expanded, onSelect }: { item: FindingView; expanded: boolean; onSelect: () => void }) {
  const { t } = useI18n();
  const { finding } = item;
  return (
    <Expandable
      id={`finding-${finding.id}`}
      expanded={expanded}
      onToggle={onSelect}
      accent={isSeverity(finding.severity) ? ACCENT_CLASSES[finding.severity] : undefined}
      header={
        <>
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={finding.severity} />
            {!item.positioned && <Badge className="bg-muted text-muted-foreground">{t("audit.unpositioned")}</Badge>}
          </div>
          <p className="font-medium">{finding.rule_name ?? finding.description}</p>
          {finding.quote && (
            <p className="line-clamp-2 text-muted-foreground">«{asOneLine(finding.quote)}»</p>
          )}
        </>
      }
    >
      <FindingCard item={item} />
    </Expandable>
  );
}

const joinNameAndCode = (name: string | null | undefined, code: string | null | undefined) =>
  [name, code && `(${code})`].filter(Boolean).join(" ");

export function FindingCard({ item }: { item: FindingView }) {
  const { t } = useI18n();
  const { finding, analysis } = item;
  const act = joinNameAndCode(finding.legal_act_title, finding.legal_act_code);
  const rule = joinNameAndCode(finding.rule_name, finding.rule_code);
  return (
    <dl className="space-y-3 pt-3 text-sm">
      <Field label={t("finding.description")}>{finding.description}</Field>
      <Field label={t("finding.explanation")}>
        {analysis?.explanation ?? <span className="text-muted-foreground">{t("finding.noExplanation")}</span>}
      </Field>
      {finding.quote && <Field label={t("finding.quote")}>«{withParagraphBreaks(finding.quote)}»</Field>}
      {finding.norm_quote && <NormField quote={finding.norm_quote} />}
      <Field label={t("finding.legalAct")}>{act || t("finding.deleted")}</Field>
      <Field label={t("finding.rule")}>{rule || t("finding.deleted")}</Field>
      {item.recommendation && (
        <Field label={t("finding.recommendation")}>
          <p className="rounded-md bg-accent p-2">{item.recommendation}</p>
        </Field>
      )}
    </dl>
  );
}

function NormField({ quote }: { quote: string }) {
  const { t } = useI18n();
  return (
    <Field label={t("finding.norm")}>
      <blockquote className="border-l-2 pl-3 italic">{asOneLine(quote)}</blockquote>
    </Field>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="whitespace-pre-wrap">{children}</dd>
    </div>
  );
}

/**
 * Applied rules that gave no finding. The report keeps only their name and code, so the details come
 * from the current rule, read when its card is opened. Which text satisfied each rule is not stored by
 * the audit.
 */
export function PassedRules({ rules }: { rules: PassedRule[] | null }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (key: string) =>
    setExpanded((keys) => {
      const next = new Set(keys);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <section aria-label={t("audit.passedTitle")} className="mt-4 space-y-2">
      <h3 className="px-1 text-sm font-semibold">{t("audit.passedTitle")}</h3>
      {rules === null ? (
        <p className="px-1 text-sm text-muted-foreground">{t("audit.passedUnknown")}</p>
      ) : rules.length === 0 ? (
        <p className="px-1 text-sm text-muted-foreground">{t("audit.passedEmpty")}</p>
      ) : (
        <ul className="space-y-2">
          {rules.map((rule, index) => {
            const key = String(rule.ruleId ?? rule.ruleCode ?? index);
            return (
              <li key={key}>
                <Expandable
                  id={`passed-${key}`}
                  expanded={expanded.has(key)}
                  onToggle={() => toggle(key)}
                  accent="border-l-success"
                  header={
                    <div className="flex items-start gap-2">
                      <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
                      <div className="min-w-0 space-y-0.5">
                        <p className="font-medium">{rule.name ?? rule.ruleCode}</p>
                        {rule.legalAct && <p className="text-muted-foreground">{rule.legalAct}</p>}
                      </div>
                    </div>
                  }
                >
                  <PassedRuleCard rule={rule} />
                </Expandable>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** Rendered only while the card is open, so each opened rule is one request. */
function PassedRuleCard({ rule }: { rule: PassedRule }) {
  const { t } = useI18n();
  const { ruleId } = rule;
  const query = useQuery({
    queryKey: queryKeys.rule(ruleId ?? 0),
    queryFn: ({ signal }) => api.rules.get(ruleId!, signal),
    enabled: ruleId !== undefined,
  });
  // The rule may have been deleted since the audit; its id is then empty or unknown.
  const deleted = ruleId === undefined || hasErrorCode(query.error, "rule_not_found");
  const current = query.data;
  return (
    <dl className="space-y-3 pt-3 text-sm">
      {!deleted && query.isPending && <p role="status">{t("table.loading")}</p>}
      {!deleted && query.isError && <ErrorAlert error={query.error} onRetry={() => void query.refetch()} />}
      {deleted && <p className="text-muted-foreground">{t("audit.passedDeleted")}</p>}
      {current && (
        <>
          <Field label={t("finding.description")}>{current.description || current.name}</Field>
          {current.source_quote && <NormField quote={current.source_quote} />}
          <Field label={t("finding.severity")}>
            <SeverityBadge severity={current.severity} />
          </Field>
        </>
      )}
      {rule.legalAct && <Field label={t("finding.legalAct")}>{rule.legalAct}</Field>}
      <Field label={t("finding.rule")}>{joinNameAndCode(rule.name, rule.ruleCode)}</Field>
      {rule.rejected.map((candidate, index) => (
        <Field key={index} label={t("audit.passedRejected")}>
          {candidate.quote && <span className="font-medium">«{asOneLine(candidate.quote)}»</span>}
          {candidate.reason && <span className="block">{candidate.reason}</span>}
        </Field>
      ))}
      {current && <p className="text-xs text-muted-foreground">{t("audit.passedCurrent")}</p>}
    </dl>
  );
}
