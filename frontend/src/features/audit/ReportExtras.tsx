import type { ReactNode } from "react";

import { useI18n } from "@/i18n";

import type { ReportView } from "./reportModel";

/** Secondary report data, collapsed by default. */
export function ReportExtras({ view }: { view: ReportView }) {
  const { t, tOptional } = useI18n();
  const { selection } = view;
  return (
    <div className="space-y-2">
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
