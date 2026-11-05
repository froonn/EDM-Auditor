import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/endpoints";
import type { DocumentType, DocumentTypeSuggestion } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel, Textarea } from "@/components/ui/form";
import { invalidateCatalog, queryKeys } from "@/features/queries";
import { useI18n } from "@/i18n";

/** The API accepts the same pattern; checking it here explains the rule before sending. */
export const TYPE_CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

export function DocumentTypesPage() {
  const { t } = useI18n();
  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("types.title")}</h1>
        <p className="text-muted-foreground">{t("types.description")}</p>
      </div>
      <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start gap-4">
        <Catalog />
        <div className="space-y-4">
          <Suggestions />
          <NewType />
        </div>
      </div>
    </section>
  );
}

function Suggestions() {
  const { t } = useI18n();
  const suggestions = useQuery({
    queryKey: queryKeys.suggestions,
    queryFn: ({ signal }) => api.documentTypes.suggestions(signal),
  });
  return (
    <Panel title={t("types.suggestions")}>
      {suggestions.isError && <ErrorAlert error={suggestions.error} onRetry={() => void suggestions.refetch()} />}
      {suggestions.isPending && <p role="status">{t("table.loading")}</p>}
      {suggestions.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("types.suggestionsEmpty")}</p>}
      <ul className="space-y-3">
        {suggestions.data?.map((suggestion) => (
          <li key={suggestion.id}>
            <SuggestionItem suggestion={suggestion} />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function SuggestionItem({ suggestion }: { suggestion: DocumentTypeSuggestion }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState(suggestion.name);
  const [description, setDescription] = useState(suggestion.reason);
  const onSettled = () => invalidateCatalog(queryClient);
  const accept = useMutation({
    mutationFn: () =>
      api.documentTypes.acceptSuggestion(suggestion.id, {
        code: code.trim(),
        name: name.trim() || undefined,
        description: description.trim() || undefined,
      }),
    onSettled,
  });
  const dismiss = useMutation({ mutationFn: () => api.documentTypes.dismissSuggestion(suggestion.id), onSettled });
  const busy = accept.isPending || dismiss.isPending;
  const codeValid = TYPE_CODE_PATTERN.test(code.trim());

  return (
    <article className="space-y-3 rounded-md border p-3 text-sm">
      <div>
        <p className="font-medium">{suggestion.name}</p>
        <p className="text-muted-foreground">{t("types.suggestionReason", { reason: suggestion.reason })}</p>
        <p className="text-xs text-muted-foreground">{t("types.suggestionSeen", { count: suggestion.occurrences })}</p>
      </div>
      <fieldset disabled={busy} className="grid grid-cols-2 gap-3">
        <FormField label={t("types.field.code")} hint={t("types.field.codeHint")}>
          <Input value={code} onChange={(event) => setCode(event.target.value)} maxLength={100} />
        </FormField>
        <FormField label={t("types.field.name")}>
          <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} />
        </FormField>
        <FormField label={t("types.field.description")} className="col-span-2">
          <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} />
        </FormField>
        <div className="col-span-2 flex gap-2">
          <Button size="sm" onClick={() => accept.mutate()} disabled={!codeValid}>
            {t("types.accept")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => dismiss.mutate()}>
            {t("types.dismiss")}
          </Button>
        </div>
      </fieldset>
      {code.trim() && !codeValid && <p className="text-destructive">{t("types.badCode")}</p>}
      {accept.isError && <ErrorAlert error={accept.error} />}
      {dismiss.isError && <ErrorAlert error={dismiss.error} />}
    </article>
  );
}

function Catalog() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const catalog = useQuery({ queryKey: queryKeys.catalog, queryFn: ({ signal }) => api.documentTypes.listAll(signal) });
  const [editing, setEditing] = useState<string | null>(null);
  const [deactivating, setDeactivating] = useState<DocumentType | null>(null);
  const onSettled = () => invalidateCatalog(queryClient);
  const deactivate = useMutation({ mutationFn: (code: string) => api.documentTypes.deactivate(code), onSettled });
  const reactivate = useMutation({
    mutationFn: (type: DocumentType) =>
      api.documentTypes.create({ code: type.code, name: type.name, description: type.description }),
    onSettled,
  });

  return (
    <Panel title={t("types.catalog")}>
      {deactivate.isError && <ErrorAlert error={deactivate.error} showServerMessage />}
      {reactivate.isError && <ErrorAlert error={reactivate.error} />}
      {catalog.isError ? (
        <ErrorAlert error={catalog.error} onRetry={() => void catalog.refetch()} />
      ) : (
        <DataTable
          rows={catalog.data}
          rowKey={(type) => type.code}
          isLoading={catalog.isPending}
          columns={[
            {
              key: "type",
              header: t("types.column.type"),
              className: "w-64",
              cell: (type) => (
                <div>
                  <p className="font-medium">{type.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">{type.code}</p>
                </div>
              ),
            },
            {
              key: "description",
              header: t("types.column.description"),
              cell: (type) =>
                editing === type.code ? (
                  <EditType type={type} onDone={() => setEditing(null)} />
                ) : (
                  <span className="whitespace-pre-wrap">{type.description}</span>
                ),
            },
            {
              key: "state",
              header: t("types.column.state"),
              className: "w-0 whitespace-nowrap",
              cell: (type) => (
                <div className="flex flex-col items-start gap-2">
                  {type.is_active ? (
                    <Badge className="border-success/30 bg-success-muted text-success">{t("types.active")}</Badge>
                  ) : (
                    <Badge className="bg-muted text-muted-foreground">{t("types.inactive")}</Badge>
                  )}
                  <div className="flex gap-1">
                    {type.is_active && editing !== type.code && (
                      <Button size="sm" variant="ghost" onClick={() => setEditing(type.code)}>
                        {t("action.edit")}
                      </Button>
                    )}
                    {type.is_active ? (
                      <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeactivating(type)}>
                        {t("types.deactivate")}
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => reactivate.mutate(type)} disabled={reactivate.isPending}>
                        {t("types.reactivate")}
                      </Button>
                    )}
                  </div>
                </div>
              ),
            },
          ]}
        />
      )}
      <ConfirmDialog
        open={deactivating !== null}
        onOpenChange={(open) => !open && setDeactivating(null)}
        title={t("types.deactivateTitle", { name: deactivating?.name ?? "" })}
        description={t("types.deactivateDescription")}
        confirmLabel={t("types.deactivate")}
        destructive
        onConfirm={() => deactivating && deactivate.mutate(deactivating.code)}
      />
    </Panel>
  );
}

function EditType({ type, onDone }: { type: DocumentType; onDone: () => void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [name, setName] = useState(type.name);
  const [description, setDescription] = useState(type.description);
  const save = useMutation({
    mutationFn: () => api.documentTypes.update(type.code, { name: name.trim(), description: description.trim() }),
    onSuccess: onDone,
    onSettled: () => invalidateCatalog(queryClient),
  });
  return (
    <fieldset disabled={save.isPending} className="space-y-2">
      <FormField label={t("types.field.name")}>
        <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} />
      </FormField>
      <FormField label={t("types.field.description")} hint={t("types.field.descriptionHint")}>
        <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} />
      </FormField>
      <div className="flex gap-2">
        <Button size="sm" onClick={() => save.mutate()} disabled={!name.trim() || !description.trim()}>
          {t("action.save")}
        </Button>
        <Button size="sm" variant="outline" onClick={onDone}>
          {t("action.cancel")}
        </Button>
      </div>
      {save.isError && <ErrorAlert error={save.error} />}
    </fieldset>
  );
}

function NewType() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () => api.documentTypes.create({ code: code.trim(), name: name.trim(), description: description.trim() }),
    onSuccess: () => {
      setCode("");
      setName("");
      setDescription("");
    },
    onSettled: () => invalidateCatalog(queryClient),
  });
  const codeValid = TYPE_CODE_PATTERN.test(code.trim());
  return (
    <Panel title={t("types.add")}>
      <fieldset disabled={create.isPending} className="grid grid-cols-2 gap-3">
        <FormField label={t("types.field.code")} hint={t("types.field.codeHint")}>
          <Input value={code} onChange={(event) => setCode(event.target.value)} maxLength={100} />
        </FormField>
        <FormField label={t("types.field.name")}>
          <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} />
        </FormField>
        <FormField label={t("types.field.description")} hint={t("types.field.descriptionHint")} className="col-span-2">
          <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} />
        </FormField>
        <div className="col-span-2">
          <Button onClick={() => create.mutate()} disabled={!codeValid || !name.trim() || !description.trim()}>
            {t("action.create")}
          </Button>
        </div>
      </fieldset>
      {code.trim() && !codeValid && <p className="text-sm text-destructive">{t("types.badCode")}</p>}
      {create.isError && <ErrorAlert error={create.error} />}
    </Panel>
  );
}
