import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/endpoints";
import type { DocumentDetail } from "@/api/types";
import { Can } from "@/auth/Can";
import { StatusBadge } from "@/components/badges";
import { ErrorAlert } from "@/components/ErrorAlert";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { invalidateDocument, useDocumentTypes } from "@/features/queries";
import { useI18n } from "@/i18n";

/** Confirms the document types the automatic rule selection depends on. */
export function ClassificationPanel({ document }: { document: DocumentDetail }) {
  const { t, tOptional, formatNumber } = useI18n();
  const types = useDocumentTypes();
  const queryClient = useQueryClient();
  const confirmed = document.confirmed_document_types ?? [];
  const [chosen, setChosen] = useState<ReadonlySet<string>>(() => new Set(confirmed));
  const [saved, setSaved] = useState(false);

  const onSettled = () => invalidateDocument(queryClient, document.id);
  const save = useMutation({
    mutationFn: (codes: string[]) => api.documents.setTypes(document.id, codes),
    onSuccess: (result) => {
      setChosen(new Set(result.confirmed_document_types ?? []));
      setSaved(true);
    },
    onSettled,
  });
  const reclassify = useMutation({
    mutationFn: () => api.documents.classify(document.id),
    onSuccess: (result) => setChosen(new Set(result.confirmed_document_types ?? [])),
    onSettled,
  });
  const busy = save.isPending || reclassify.isPending;
  const percent = (value: number) => formatNumber(value, { style: "percent", maximumFractionDigits: 0 });
  const source = document.classification_source && tOptional(`classification.source.${document.classification_source}`);
  const candidates = document.candidate_document_types ?? [];
  const toggle = (code: string) => {
    setSaved(false);
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{t("classification.title")}</h2>
        <StatusBadge kind="classification" status={document.classification_status ?? "unknown"} />
        {source && <span className="text-muted-foreground">{source}</span>}
        {typeof document.classification_confidence === "number" && (
          <span className="text-muted-foreground">
            {t("classification.confidence", { value: percent(document.classification_confidence) })}
          </span>
        )}
      </div>
      <p>
        {t("classification.confirmed")}:{" "}
        {confirmed.length > 0 ? confirmed.map(types.typeName).join(", ") : t("classification.none")}
      </p>
      <div>
        <p className="text-muted-foreground">{t("classification.candidates")}:</p>
        {candidates.length > 0 ? (
          <ul className="list-inside list-disc">
            {candidates.map((item) => (
              <li key={item.code}>
                {types.typeName(item.code)} — {t("classification.confidence", { value: percent(item.confidence) })}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">{t("classification.noCandidates")}</p>
        )}
      </div>
      <Can permission="documents.upload">
        <fieldset className="space-y-2" disabled={busy}>
          <legend className="sr-only">{t("classification.confirmed")}</legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {(types.data ?? [])
              .filter((type) => type.is_active)
              .map((type) => (
                <label key={type.code} className="flex items-center gap-2" title={type.description}>
                  <input type="checkbox" checked={chosen.has(type.code)} onChange={() => toggle(type.code)} />
                  {type.name}
                </label>
              ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => save.mutate([...chosen])} disabled={chosen.size === 0}>
              {t("classification.save")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => save.mutate([])}>
              {t("classification.reset")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => reclassify.mutate()} title={t("classification.reclassifyHint")}>
              {t("classification.reclassify")}
            </Button>
          </div>
        </fieldset>
      </Can>
      {types.isError && <ErrorAlert error={types.error} onRetry={() => void types.refetch()} />}
      {saved && !save.isPending && <p role="status" className="text-success">{t("classification.saved")}</p>}
      {reclassify.isPending && <LongOperation label={t("classification.running")} />}
      {save.isError && <ErrorAlert error={save.error} />}
      {reclassify.isError && <ErrorAlert error={reclassify.error} onRetry={() => reclassify.mutate()} />}
    </section>
  );
}
