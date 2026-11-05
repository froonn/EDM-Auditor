import { RotateCw, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

import { describeError } from "./errorMessage";

interface ErrorAlertProps {
  error: unknown;
  /** Shows a retry button. Requests that call the model are repeated only by the user. */
  onRetry?: () => void;
  retrying?: boolean;
  className?: string;
}

export function ErrorAlert({ error, onRetry, retrying = false, className }: ErrorAlertProps) {
  const i18n = useI18n();
  const view = describeError(error, i18n);
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border p-4 text-sm",
        view.isWarning ? "border-warning bg-warning-muted" : "border-destructive bg-danger-muted",
        className,
      )}
    >
      <TriangleAlert
        aria-hidden
        className={cn("mt-0.5 size-5 shrink-0", view.isWarning ? "text-warning" : "text-destructive")}
      />
      <div className="min-w-0 flex-1 space-y-2">
        <p className="font-medium">{i18n.t(view.isWarning ? "error.warningTitle" : "error.title")}</p>
        <p>{view.message}</p>
        {view.details && (
          <details className="text-muted-foreground">
            <summary className="cursor-pointer">{i18n.t("action.details")}</summary>
            <p className="mt-1 font-mono text-xs break-words">{view.details}</p>
          </details>
        )}
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
            <RotateCw aria-hidden className={cn(retrying && "animate-spin")} />
            {i18n.t("action.retry")}
          </Button>
        )}
      </div>
    </div>
  );
}
