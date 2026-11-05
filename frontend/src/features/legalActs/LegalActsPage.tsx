import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/endpoints";
import type { LegalAct } from "@/api/types";
import { StatusBadge } from "@/components/badges";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorAlert } from "@/components/ErrorAlert";
import { FileDropZone } from "@/components/FileDropZone";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel } from "@/components/ui/form";
import { invalidateCatalog, queryKeys, useDocumentTypes } from "@/features/queries";
import { TypeChecklist } from "@/features/shared/TypeChecklist";
import { useI18n } from "@/i18n";

const PAGE_SIZE = 20;

export function LegalActsPage() {
  const { t } = useI18n();
  const { typeName } = useDocumentTypes();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");

  // Search after a short pause in typing.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setApplied(search.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const request = { limit: PAGE_SIZE, offset, search: applied };
  const acts = useQuery({
    queryKey: queryKeys.legalActPage(request),
    queryFn: ({ signal }) => api.legalActs.list(request, signal),
    placeholderData: keepPreviousData,
  });

  const columns: Column<LegalAct>[] = [
    {
      key: "act",
      header: t("legalActs.column.act"),
      cell: (act) => (
        <div>
          <Link to={`/legal-acts/${act.id}`} className="font-medium text-primary hover:underline">
            {act.title}
          </Link>
          <p className="text-xs text-muted-foreground">
            {[act.code, act.number].filter(Boolean).join(" · ")}
          </p>
        </div>
      ),
    },
    {
      key: "status",
      header: t("legalActs.column.status"),
      cell: (act) => (
        <div className="space-y-1">
          <StatusBadge kind="legalAct" status={act.processing_status ?? "uploaded"} />
          {(act.chunks_total ?? 0) > 0 && (
            <p className="text-xs text-muted-foreground">
              {t("legalActs.chunks", { processed: act.chunks_processed ?? 0, total: act.chunks_total ?? 0 })}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "rules",
      header: t("legalActs.column.rules"),
      cell: (act) => t("legalActs.rulesCount", { accepted: act.rules_accepted ?? 0, rejected: act.rules_rejected ?? 0 }),
    },
    {
      key: "types",
      header: t("legalActs.column.types"),
      cell: (act) =>
        (act.document_types ?? []).length > 0 ? (
          (act.document_types ?? []).map(typeName).join(", ")
        ) : (
          <span className="text-muted-foreground">{t("legalActs.allTypes")}</span>
        ),
    },
  ];

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("legalActs.title")}</h1>
        <p className="max-w-4xl text-muted-foreground">{t("legalActs.description")}</p>
      </div>
      <UploadLegalAct />
      <div className="flex items-end gap-3">
        <FormField label={t("action.search")} className="w-80">
          <Input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("legalActs.searchPlaceholder")}
          />
        </FormField>
      </div>
      {acts.isError ? (
        <ErrorAlert error={acts.error} onRetry={() => void acts.refetch()} retrying={acts.isFetching} />
      ) : (
        <DataTable
          columns={columns}
          rows={acts.data?.items}
          rowKey={(act) => act.id}
          isLoading={acts.isPending}
          emptyText={t("legalActs.empty")}
          pagination={acts.data && { limit: PAGE_SIZE, offset, total: acts.data.total, onOffsetChange: setOffset }}
        />
      )}
    </section>
  );
}

function UploadLegalAct() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string>();
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [number, setNumber] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [types, setTypes] = useState<string[]>([]);

  const upload = useMutation({
    mutationFn: (selected: File) =>
      api.legalActs.upload(selected, {
        code: code.trim(),
        title: title.trim(),
        number: number.trim(),
        source_url: sourceUrl.trim(),
        document_types: types,
      }),
    onSuccess: () => {
      setFile(null);
      setCode("");
      setTitle("");
      setNumber("");
      setSourceUrl("");
      setTypes([]);
    },
    // A failed extraction still saves the act, so the list is refreshed either way.
    onSettled: () => invalidateCatalog(queryClient),
  });

  const choose = (selected: File | undefined) => {
    upload.reset();
    if (selected && !selected.name.toLowerCase().endsWith(".txt")) {
      setFileError(t("legalActs.onlyTxt"));
      setFile(null);
      return;
    }
    setFileError(undefined);
    setFile(selected ?? null);
  };
  const submit = () => file && upload.mutate(file);
  const ready = Boolean(file && code.trim() && title.trim());
  const failed = upload.data && upload.data.processing_status === "failed";

  return (
    <Panel title={t("legalActs.upload")}>
      <fieldset disabled={upload.isPending} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t("legalActs.field.code")} hint={t("legalActs.field.codeHint")}>
            <Input value={code} onChange={(event) => setCode(event.target.value)} maxLength={100} />
          </FormField>
          <FormField label={t("legalActs.field.title")}>
            <Input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={500} />
          </FormField>
          <FormField label={t("legalActs.field.number")}>
            <Input value={number} onChange={(event) => setNumber(event.target.value)} maxLength={100} />
          </FormField>
          <FormField label={t("legalActs.field.sourceUrl")}>
            <Input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} maxLength={1000} />
          </FormField>
        </div>
        <TypeChecklist label={t("legalActs.field.types")} value={types} onChange={setTypes} />
        <p className="text-xs text-muted-foreground">{t("legalActs.field.typesHint")}</p>
        <FileDropZone
          accept={[".txt"]}
          hint={t("legalActs.fileHint")}
          file={file}
          onSelect={choose}
          disabled={upload.isPending}
          inputLabel={t("legalActs.field.file")}
        />
        <Button onClick={submit} disabled={!ready}>
          {t("legalActs.uploadSubmit")}
        </Button>
      </fieldset>
      {fileError && (
        <p role="alert" className="text-sm text-destructive">
          {fileError}
        </p>
      )}
      {upload.isPending && <LongOperation label={t("legalActs.uploadRunning")} />}
      {upload.isError && (
        <div className="space-y-1">
          <ErrorAlert error={upload.error} />
          <p className="text-xs text-muted-foreground">{t("legalActs.uploadErrorHint")}</p>
        </div>
      )}
      {upload.data && (
        <p role="status" className={failed ? "text-sm text-warning" : "text-sm text-success"}>
          {failed ? (
            t("legalActs.uploadFailed")
          ) : (
            t("legalActs.uploadDone", {
              title: upload.data.title,
              accepted: upload.data.rules_accepted ?? 0,
              rejected: upload.data.rules_rejected ?? 0,
            })
          )}{" "}
          <Link to={`/legal-acts/${upload.data.id}`} className="text-primary underline">
            {upload.data.code}
          </Link>
        </p>
      )}
    </Panel>
  );
}
