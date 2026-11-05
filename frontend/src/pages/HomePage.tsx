import { useQuery } from "@tanstack/react-query";
import { CircleCheck } from "lucide-react";

import { api } from "@/api/endpoints";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";

export function HomePage() {
  const { t } = useI18n();
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => api.health(signal) });

  return (
    <section className="max-w-2xl space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("home.title")}</h1>
        <p className="text-muted-foreground">{t("home.description")}</p>
      </div>
      {health.isPending && <p role="status">{t("home.checking")}</p>}
      {health.isError && (
        <ErrorAlert error={health.error} onRetry={() => void health.refetch()} retrying={health.isFetching} />
      )}
      {health.isSuccess && (
        <div className="flex items-center gap-3 rounded-lg border border-success/30 bg-success-muted p-4 text-sm">
          <CircleCheck aria-hidden className="size-5 text-success" />
          <span className="flex-1">{t("home.ok")}</span>
          <Button variant="outline" size="sm" onClick={() => void health.refetch()} disabled={health.isFetching}>
            {t("home.checkAgain")}
          </Button>
        </div>
      )}
    </section>
  );
}
