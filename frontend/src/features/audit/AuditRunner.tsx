import { Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "@/api/client";
import type { AuditSelection, DocumentItem } from "@/api/types";
import { Can } from "@/auth/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorAlert } from "@/components/ErrorAlert";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { useRunAudit } from "@/features/queries";
import { useI18n } from "@/i18n";

interface AuditRunnerProps {
  document: Pick<DocumentItem, "id" | "status">;
  /** Without a selection the server uses the automatic mode. */
  selection?: AuditSelection;
  label?: string;
  disabled?: boolean;
}

/**
 * The audit button with its progress and errors. A document already in `processing` asks for a
 * confirmation: the status stays forever if the server stopped during an audit, so the button is
 * never blocked completely.
 */
export function AuditRunner({ document, selection, label, disabled = false }: AuditRunnerProps) {
  const { t } = useI18n();
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

  return (
    <Can permission="audit.run">
      <div className="space-y-3">
        <Button onClick={start} disabled={disabled || audit.isPending}>
          <Play aria-hidden />
          {label ?? t("audit.run")}
        </Button>
        {audit.isPending && <LongOperation label={t("audit.running")} />}
        {audit.isError && !redirected && <ErrorAlert error={audit.error} onRetry={run} retrying={audit.isPending} />}
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title={t("audit.processingConfirmTitle")}
          description={t("audit.processingConfirm")}
          confirmLabel={t("audit.processingConfirmAction")}
          onConfirm={run}
        />
      </div>
    </Can>
  );
}
