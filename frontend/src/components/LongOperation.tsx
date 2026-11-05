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
    <div role="status" aria-live="polite" className="overflow-hidden rounded-lg border border-primary/30 bg-accent">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm">
        <LoaderCircle aria-hidden className="size-5 shrink-0 animate-spin text-primary" />
        <p className="font-medium">{label ?? t("operation.running")}</p>
        <p className="text-muted-foreground tabular-nums">{t("operation.elapsed", { seconds })}</p>
        <p className="ml-auto text-xs text-muted-foreground">{t("operation.keepOpen")}</p>
      </div>
      {/* The API reports no progress, so the bar only shows that the request is still running. */}
      <div aria-hidden className="h-1 bg-primary/15">
        <div className="h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] bg-primary motion-reduce:animate-none" />
      </div>
    </div>
  );
}
