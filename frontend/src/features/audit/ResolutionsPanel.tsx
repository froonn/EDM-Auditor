import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api } from "@/api/endpoints";
import type { Resolution, ResolutionDecision } from "@/api/types";
import { Can } from "@/auth/Can";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField, Panel, Select, Textarea } from "@/components/ui/form";
import { invalidateDocument, queryKeys } from "@/features/queries";
import { useI18n } from "@/i18n";

const DECISIONS: readonly ResolutionDecision[] = ["approved", "needs_revision", "rejected"];

export function ResolutionBadge({ decision }: { decision: string }) {
  const { tOptional } = useI18n();
  const label = tOptional(`resolutions.decision.${decision}`) ?? decision;
  const style =
    decision === "approved"
      ? "border-success/30 bg-success-muted text-success"
      : decision === "rejected"
        ? "border-destructive/30 bg-destructive/10 text-destructive"
        : "border-warning/40 bg-warning-muted text-warning-foreground";
  return <Badge className={style}>{label}</Badge>;
}

export function ResolutionsPanel({ reportId, documentId }: { reportId: number; documentId: number }) {
  const { t, formatDateTime } = useI18n();
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState<ResolutionDecision>("approved");
  const [comment, setComment] = useState("");

  const resolutions = useQuery<Resolution[]>({
    queryKey: queryKeys.resolutions(reportId),
    queryFn: ({ signal }) => api.reports.resolutions(reportId, signal),
  });

  const create = useMutation({
    mutationFn: () => api.reports.createResolution(reportId, { decision, comment: comment.trim() }),
    onSuccess: () => {
      setComment("");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.resolutions(reportId) });
      void invalidateDocument(queryClient, documentId);
    },
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Panel title={t("resolutions.title")}>
      {resolutions.isPending && <p role="status" className="text-sm text-muted-foreground">{t("table.loading")}</p>}
      {resolutions.isError && <ErrorAlert error={resolutions.error} onRetry={() => void resolutions.refetch()} />}
      {resolutions.data && resolutions.data.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("resolutions.empty")}</p>
      )}
      {resolutions.data && resolutions.data.length > 0 && (
        <ul className="space-y-2">
          {resolutions.data.map((item) => (
            <li key={item.id} className="space-y-1 rounded-md border bg-muted/30 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <ResolutionBadge decision={item.decision} />
                  <span className="font-medium">{item.author_name}</span>
                </div>
                <span className="text-xs text-muted-foreground">{formatDateTime(item.created_at)}</span>
              </div>
              {item.comment && <p className="whitespace-pre-wrap text-muted-foreground">{item.comment}</p>}
            </li>
          ))}
        </ul>
      )}

      <Can permission="resolutions.write">
        <form onSubmit={handleSubmit} className="space-y-3 border-t pt-3">
          <div className="grid grid-cols-[16rem_minmax(0,1fr)] items-start gap-3">
            <FormField label={t("resolutions.decisionLabel")}>
              <Select
                value={decision}
                onChange={(event) => setDecision(event.target.value as ResolutionDecision)}
                disabled={create.isPending}
              >
                {DECISIONS.map((value) => (
                  <option key={value} value={value}>
                    {t(`resolutions.decision.${value}`)}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label={t("resolutions.commentLabel")}>
              <Textarea
                rows={2}
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder={t("resolutions.commentPlaceholder")}
                disabled={create.isPending}
              />
            </FormField>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={create.isPending}>
              {t("resolutions.submit")}
            </Button>
            {create.isSuccess && (
              <span role="status" className="text-sm text-success">
                {t("resolutions.saved")}
              </span>
            )}
          </div>
          {create.isError && <ErrorAlert error={create.error} />}
        </form>
      </Can>
    </Panel>
  );
}
