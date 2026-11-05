import { Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "@/api/client";
import type { AuditSelection, DocumentItem } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorAlert } from "@/components/ErrorAlert";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { useRunAudit } from "@/features/queries";
import { useI18n } from "@/i18n";

export type AuditRunner = ReturnType<typeof useAuditRunner>;

/**
 * Starts an audit. The button and the progress are separate components, so a page can keep the
 * button in its header and show the progress across the full width below.
 *
 * A document already in `processing` asks for a confirmation: the status stays forever if the
 * server stopped during an audit, so the button is never blocked completely.
 */
export function useAuditRunner(document: Pick<DocumentItem, "id" | "status">, selection?: AuditSelection) {
  const navigate = useNavigate();
  const audit = useRunAudit(document);
  const [confirming, setConfirming] = useState(false);

  const run = () =>
    audit.mutate(selection, {
      onSuccess: (result) =>
        void navigate(`/documents/${document.id}/audit?report=${result.report_id}`, { replace: true }),
      onError: (error) => {
        if (error instanceof ApiError && error.code === "audit_configuration_required" && !selection) {
          void navigate(`/documents/${document.id}/configure`, { state: { configurationRequired: true } });
        }
      },
    });
  const start = () => (document.status === "processing" ? setConfirming(true) : run());
  const redirected =
    audit.error instanceof ApiError && audit.error.code === "audit_configuration_required" && !selection;

  return { audit, run, start, redirected, confirming, setConfirming };
}

export function AuditRunButton({
  runner,
  label,
  disabled = false,
}: {
  runner: AuditRunner;
  label?: string;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  return (
    <>
      <Button onClick={runner.start} disabled={disabled || runner.audit.isPending}>
        <Play aria-hidden />
        {label ?? t("audit.run")}
      </Button>
      <ConfirmDialog
        open={runner.confirming}
        onOpenChange={runner.setConfirming}
        title={t("audit.processingConfirmTitle")}
        description={t("audit.processingConfirm")}
        confirmLabel={t("audit.processingConfirmAction")}
        onConfirm={runner.run}
      />
    </>
  );
}

/** The progress or the error of the audit, meant for the full width of the page. */
export function AuditRunStatus({ runner }: { runner: AuditRunner }) {
  const { t } = useI18n();
  const { audit } = runner;
  if (audit.isPending) return <LongOperation label={t("audit.running")} />;
  if (audit.isError && !runner.redirected) {
    return <ErrorAlert error={audit.error} onRetry={runner.run} retrying={audit.isPending} />;
  }
  return null;
}
