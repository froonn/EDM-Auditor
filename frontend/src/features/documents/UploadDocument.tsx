import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/endpoints";
import type { DocumentItem } from "@/api/types";
import { ErrorAlert } from "@/components/ErrorAlert";
import { FileDropZone } from "@/components/FileDropZone";
import { LongOperation } from "@/components/LongOperation";
import { Button } from "@/components/ui/button";
import { queryKeys, useDocumentTypes } from "@/features/queries";
import { useI18n, type I18n } from "@/i18n";

const ACCEPTED_EXTENSIONS = [".txt", ".docx", ".pdf"];
/** The server default (EDM_MAX_UPLOAD_BYTES). The server checks its own limit as well. */
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

export function validateUpload(file: File, i18n: Pick<I18n, "t" | "formatNumber">): string | undefined {
  const name = file.name;
  const size = i18n.t("upload.sizeMb", { value: i18n.formatNumber(MAX_UPLOAD_BYTES / 1024 / 1024) });
  if (!ACCEPTED_EXTENSIONS.some((extension) => name.toLowerCase().endsWith(extension))) {
    return i18n.t("upload.badFormat", { name });
  }
  if (file.size === 0) return i18n.t("upload.emptyFile", { name });
  if (file.size > MAX_UPLOAD_BYTES) return i18n.t("upload.tooLarge", { name, size });
  return undefined;
}

export function UploadDocument() {
  const i18n = useI18n();
  const { t, formatNumber } = i18n;
  const { typeName } = useDocumentTypes();
  const queryClient = useQueryClient();
  const titleId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [invalid, setInvalid] = useState<string>();
  const [uploaded, setUploaded] = useState<DocumentItem>();

  const upload = useMutation({
    mutationFn: ({ selected, name }: { selected: File; name: string }) =>
      api.documents.upload(selected, name.trim() || undefined),
    onSuccess: (document) => {
      setUploaded(document);
      setFile(null);
      setTitle("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments });
    },
  });

  const choose = (selected: File | undefined) => {
    if (!selected) return;
    setUploaded(undefined);
    upload.reset();
    const problem = validateUpload(selected, i18n);
    setInvalid(problem);
    setFile(problem ? null : selected);
  };

  const submit = () => file && upload.mutate({ selected: file, name: title });
  const size = t("upload.sizeMb", { value: formatNumber(MAX_UPLOAD_BYTES / 1024 / 1024) });

  return (
    <section aria-labelledby={`${titleId}-heading`} className="space-y-3 rounded-lg border bg-card p-4">
      <h2 id={`${titleId}-heading`} className="font-semibold">
        {t("upload.title")}
      </h2>
      <FileDropZone
        accept={ACCEPTED_EXTENSIONS}
        hint={t("upload.hint", { size })}
        file={file}
        onSelect={choose}
        disabled={upload.isPending}
      />
      <div className="flex items-end gap-3">
        <label className="flex flex-1 flex-col gap-1 text-sm">
          {t("upload.titleLabel")}
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t("upload.titlePlaceholder")}
            maxLength={255}
            className="h-9 rounded-md border bg-card px-3"
          />
        </label>
        <Button onClick={submit} disabled={!file || upload.isPending}>
          {t("upload.submit")}
        </Button>
      </div>
      {invalid && (
        <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
          <TriangleAlert aria-hidden className="size-4" />
          {invalid}
        </p>
      )}
      {upload.isPending && <LongOperation label={t("upload.running")} />}
      {upload.isError && <ErrorAlert error={upload.error} onRetry={submit} />}
      {uploaded && <UploadResult document={uploaded} typeName={typeName} />}
    </section>
  );
}

function UploadResult({ document, typeName }: { document: DocumentItem; typeName: (code: string) => string }) {
  const { t } = useI18n();
  const confirmed = document.classification_status === "classified" && !document.needs_configuration;
  return (
    <div role="status" className="flex items-start gap-3 rounded-lg border border-success/30 bg-success-muted p-4 text-sm">
      <CircleCheck aria-hidden className="mt-0.5 size-5 text-success" />
      <div className="flex-1 space-y-1">
        <p className="font-medium">{t("upload.done", { title: document.title })}</p>
        <p>
          {confirmed
            ? t("upload.typeDetected", { types: (document.confirmed_document_types ?? []).map(typeName).join(", ") })
            : t("upload.needsType")}
        </p>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link to={confirmed ? `/documents/${document.id}/audit` : `/documents/${document.id}/configure`}>
          {confirmed ? t("documents.open") : t("upload.toConfigure")}
        </Link>
      </Button>
    </div>
  );
}
