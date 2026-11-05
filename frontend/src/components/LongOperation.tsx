import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "@/i18n";

interface LongOperationProps {
  /** What is running, for example "Идёт аудит документа". */
  label?: string;
}

/**
 * Indicator for one long request. The API reports no progress, so it shows elapsed time instead of
 * a percentage.
 */
export function LongOperation({ label }: LongOperationProps) {
  const { t } = useI18n();
  const [startedAt] = useState(() => Date.now());
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  return (
    <div role="status" aria-live="polite" className="flex items-start gap-3 rounded-lg border bg-card p-4">
      <LoaderCircle aria-hidden className="mt-0.5 size-5 shrink-0 animate-spin text-primary" />
      <div className="space-y-1 text-sm">
        <p className="font-medium">{label ?? t("operation.running")}</p>
        <p className="text-muted-foreground">{t("operation.elapsed", { seconds })}</p>
        <p className="text-muted-foreground">{t("operation.keepOpen")}</p>
      </div>
    </div>
  );
}
