import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { api } from "@/api/endpoints";
import { EXPORT_FORMATS, type ExportFormat } from "@/api/types";
import { Can } from "@/auth/Can";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { browserTimeZone } from "@/lib/dates";
import { saveFile } from "@/lib/download";

/** One button per export format; the server builds the file (FR-4.4). */
export function ReportExport({ reportId }: { reportId: number }) {
  const { t } = useI18n();
  const download = useMutation({
    mutationFn: (format: ExportFormat) => api.reports.export(reportId, format, browserTimeZone()),
    onSuccess: (file) => saveFile(file.blob, file.fileName),
  });

  return (
    <Can permission="reports.export">
      <div className="ml-auto flex flex-col items-end gap-2">
        <div className="flex gap-2">
          {EXPORT_FORMATS.map((format) => (
            <Button
              key={format}
              variant="outline"
              size="sm"
              onClick={() => download.mutate(format)}
              disabled={download.isPending}
              title={t(`export.${format}.hint`)}
            >
              <Download aria-hidden />
              {download.isPending && download.variables === format ? t("export.preparing") : t(`export.${format}`)}
            </Button>
          ))}
        </div>
        {download.isError && <ErrorAlert error={download.error} showServerMessage />}
      </div>
    </Can>
  );
}
