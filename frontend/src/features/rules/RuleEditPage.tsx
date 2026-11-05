import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { hasErrorCode } from "@/api/client";
import { api } from "@/api/endpoints";
import {
  CHECK_TYPES,
  MANUAL_SCOPES,
  SEVERITIES,
  type ApplicabilityScope,
  type CheckType,
  type Rule,
} from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel, Select, Textarea } from "@/components/ui/form";
import { asOneLine } from "@/features/audit/textFormat";
import { invalidateCatalog, queryKeys, useDocumentTypes } from "@/features/queries";
import { TypeChecklist } from "@/features/shared/TypeChecklist";
import { useI18n } from "@/i18n";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { InvalidNumber, toForm, toParameters, type ParameterForm } from "./ruleParameters";

export function RuleEditPage() {
  const { id } = useParams();
  if (id === "new") return <RuleScreen rule={null} />;
  const ruleId = Number(id);
  return Number.isInteger(ruleId) && ruleId > 0 ? <ExistingRule id={ruleId} /> : <NotFoundPage />;
}

function ExistingRule({ id }: { id: number }) {
  const { t } = useI18n();
  const rule = useQuery({ queryKey: queryKeys.rule(id), queryFn: ({ signal }) => api.rules.get(id, signal) });
  // A deleted rule, or an address typed by hand.
  if (hasErrorCode(rule.error, "rule_not_found")) return <NotFoundPage />;
  if (rule.isError) return <ErrorAlert error={rule.error} onRetry={() => void rule.refetch()} />;
  if (!rule.data) return <p role="status">{t("table.loading")}</p>;
  return <RuleScreen key={rule.data.id} rule={rule.data} />;
}

function RuleScreen({ rule }: { rule: Rule | null }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const remove = useMutation({
    mutationFn: (id: number) => api.rules.remove(id),
    onSuccess: () => void navigate("/rules"),
    onSettled: () => invalidateCatalog(queryClient),
  });

  return (
    <div className="space-y-4">
      <Link to="/rules" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft aria-hidden className="size-4" />
        {t("rules.back")}
      </Link>
      <div className="flex items-start gap-4">
        <h1 className="flex-1 text-2xl font-semibold">{rule ? rule.name : t("rules.createTitle")}</h1>
        {rule && (
          <Button variant="destructive" onClick={() => setConfirmDelete(true)} disabled={remove.isPending}>
            {t("action.delete")}
          </Button>
        )}
      </div>
      {rule?.is_generated && (
        <p className="rounded-lg border border-warning bg-warning-muted p-3 text-sm">{t("rules.generatedWarning")}</p>
      )}
      {remove.isError && <ErrorAlert error={remove.error} />}
      {rule ? (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start gap-4">
          <RuleForm rule={rule} />
          <div className="space-y-4">
            {rule.source_quote && <SourceQuote rule={rule} />}
            <ApplicabilityForm rule={rule} />
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start gap-4">
          <RuleForm rule={null} />
        </div>
      )}
      {rule && (
        <ConfirmDialog
          open={confirmDelete}
          onOpenChange={setConfirmDelete}
          title={t("rules.deleteTitle", { name: rule.name })}
          description={t("rules.deleteDescription")}
          confirmLabel={t("action.delete")}
          destructive
          onConfirm={() => remove.mutate(rule.id)}
        />
      )}
    </div>
  );
}

function SourceQuote({ rule }: { rule: Rule }) {
  const { t } = useI18n();
  return (
    <Panel title={t("rules.norm")}>
      <blockquote className="border-l-2 pl-3 text-sm italic">{asOneLine(rule.source_quote ?? "")}</blockquote>
      {rule.source_location && (
        <p className="text-xs text-muted-foreground">{t("rules.location", { location: rule.source_location })}</p>
      )}
    </Panel>
  );
}

const isCheckType = (value: string): value is CheckType => (CHECK_TYPES as readonly string[]).includes(value);

function RuleForm({ rule }: { rule: Rule | null }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const acts = useQuery({ queryKey: queryKeys.legalActs, queryFn: ({ signal }) => api.legalActs.all(signal) });

  const [code, setCode] = useState("");
  const [name, setName] = useState(rule?.name ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [severity, setSeverity] = useState(rule?.severity ?? "medium");
  // A stored semantic rule cannot be saved as such: the API refuses it, so another type is offered.
  const [checkType, setCheckType] = useState<CheckType>(rule && isCheckType(rule.check_type) ? rule.check_type : "keyword");
  const [form, setForm] = useState<ParameterForm>(() => toForm(rule?.parameters ?? {}));
  const [active, setActive] = useState(rule?.is_active ?? true);
  const [actId, setActId] = useState("");
  const [scope, setScope] = useState<ApplicabilityScope>("universal");
  const [types, setTypes] = useState<string[]>([]);
  const [numberError, setNumberError] = useState(false);

  const update = (changes: Partial<ParameterForm>) => setForm((current) => ({ ...current, ...changes }));

  const save = useMutation({
    mutationFn: async () => {
      const parameters = toParameters(checkType, form);
      if (rule) {
        return api.rules.update(rule.id, {
          name: name.trim(),
          description: description.trim(),
          severity,
          check_type: checkType,
          parameters,
          is_active: active,
        });
      }
      return api.rules.create({
        rule_code: code.trim(),
        name: name.trim(),
        description: description.trim(),
        severity,
        check_type: checkType,
        parameters,
        legal_act_id: actId ? Number(actId) : null,
        applicability_scope: scope,
        document_types: scope === "typed" ? types : [],
      });
    },
    onSuccess: (saved) => {
      if (!rule) void navigate(`/rules/${saved.id}`, { replace: true });
    },
    onSettled: () => invalidateCatalog(queryClient),
  });

  const submit = () => {
    try {
      toParameters(checkType, form);
    } catch (error) {
      if (error instanceof InvalidNumber) {
        setNumberError(true);
        return;
      }
      throw error;
    }
    setNumberError(false);
    save.mutate();
  };
  const valid = name.trim() && (rule || code.trim()) && (rule || scope !== "typed" || types.length > 0);

  return (
    <Panel title={t("rules.editTitle")}>
      <fieldset disabled={save.isPending} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          {!rule && (
            <FormField label={t("rules.field.code")} hint={t("rules.field.codeHint")}>
              <Input value={code} onChange={(event) => setCode(event.target.value)} maxLength={100} />
            </FormField>
          )}
          <FormField label={t("rules.field.name")} className={rule ? "col-span-2" : undefined}>
            <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} />
          </FormField>
          <FormField label={t("rules.field.description")} className="col-span-2">
            <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} />
          </FormField>
          <FormField label={t("rules.field.severity")}>
            <Select value={severity} onChange={(event) => setSeverity(event.target.value)}>
              {SEVERITIES.map((value) => (
                <option key={value} value={value}>
                  {t(`severity.${value}`)}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label={t("rules.field.check")}>
            <Select value={checkType} onChange={(event) => setCheckType(event.target.value as CheckType)}>
              {CHECK_TYPES.map((value) => (
                <option key={value} value={value}>
                  {t(`rules.check.${value}`)}
                </option>
              ))}
            </Select>
          </FormField>
        </div>

        <ParameterFields checkType={checkType} form={form} onChange={update} />

        <FormField label={t("rules.field.recommendation")} hint={t("rules.field.recommendationHint")}>
          <Textarea value={form.recommendation} onChange={(event) => update({ recommendation: event.target.value })} rows={2} />
        </FormField>

        {!rule && (
          <div className="space-y-3">
            <FormField label={t("rules.field.act")}>
              <Select value={actId} onChange={(event) => setActId(event.target.value)}>
                <option value="">{t("common.none")}</option>
                {(acts.data ?? []).map((act) => (
                  <option key={act.id} value={act.id}>
                    {act.title} ({act.code})
                  </option>
                ))}
              </Select>
            </FormField>
            <ScopeFields scope={scope} types={types} onScope={setScope} onTypes={setTypes} />
          </div>
        )}
        {rule && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />
            {t("rules.field.active")}
          </label>
        )}
        <Button onClick={submit} disabled={!valid}>
          {rule ? t("action.save") : t("action.create")}
        </Button>
      </fieldset>
      {numberError && (
        <p role="alert" className="text-sm text-destructive">
          {t("rules.invalidNumber")}
        </p>
      )}
      {save.isSuccess && rule && <p role="status" className="text-sm text-success">{t("action.saved")}</p>}
      {/* The server explains which parameter is wrong, so its message is shown next to the form. */}
      {save.isError && <ErrorAlert error={save.error} showServerMessage />}
    </Panel>
  );
}

function ParameterFields({
  checkType,
  form,
  onChange,
}: {
  checkType: CheckType;
  form: ParameterForm;
  onChange: (changes: Partial<ParameterForm>) => void;
}) {
  const { t } = useI18n();
  switch (checkType) {
    case "keyword":
      return (
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t("rules.field.keywords")} className="col-span-2">
            <Textarea value={form.keywords} onChange={(event) => onChange({ keywords: event.target.value })} rows={3} />
          </FormField>
          <FormField label={t("rules.field.mode")}>
            <Select value={form.mode} onChange={(event) => onChange({ mode: event.target.value as ParameterForm["mode"] })}>
              <option value="forbidden">{t("rules.mode.forbidden")}</option>
              <option value="required">{t("rules.mode.required")}</option>
            </Select>
          </FormField>
          <FormField label={t("rules.field.match")}>
            <Select value={form.match} onChange={(event) => onChange({ match: event.target.value as ParameterForm["match"] })}>
              <option value="literal">{t("rules.match.literal")}</option>
              <option value="stem">{t("rules.match.stem")}</option>
              <option value="regex">{t("rules.match.regex")}</option>
            </Select>
          </FormField>
        </div>
      );
    case "regex":
      return (
        <FormField label={t("rules.field.pattern")}>
          <Input value={form.pattern} onChange={(event) => onChange({ pattern: event.target.value })} className="font-mono" />
        </FormField>
      );
    case "numeric":
      return (
        <div className="grid grid-cols-3 gap-3">
          <FormField label={t("rules.field.entity")}>
            <Select value={form.entity} onChange={(event) => onChange({ entity: event.target.value as ParameterForm["entity"] })}>
              {(["number", "duration", "money", "percent"] as const).map((entity) => (
                <option key={entity} value={entity}>
                  {t(`rules.entity.${entity}`)}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label={t("rules.field.min")}>
            <Input inputMode="decimal" value={form.min} onChange={(event) => onChange({ min: event.target.value })} />
          </FormField>
          <FormField label={t("rules.field.max")}>
            <Input inputMode="decimal" value={form.max} onChange={(event) => onChange({ max: event.target.value })} />
          </FormField>
        </div>
      );
    case "date":
      return (
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t("rules.field.after")}>
            <Input type="date" value={form.after} onChange={(event) => onChange({ after: event.target.value })} />
          </FormField>
          <FormField label={t("rules.field.before")}>
            <Input type="date" value={form.before} onChange={(event) => onChange({ before: event.target.value })} />
          </FormField>
        </div>
      );
    case "duration":
      return (
        <div className="grid grid-cols-2 gap-3">
          <FormField label={t("rules.field.minDays")}>
            <Input inputMode="numeric" value={form.minDays} onChange={(event) => onChange({ minDays: event.target.value })} />
          </FormField>
          <FormField label={t("rules.field.maxDays")}>
            <Input inputMode="numeric" value={form.maxDays} onChange={(event) => onChange({ maxDays: event.target.value })} />
          </FormField>
        </div>
      );
  }
}

function ScopeFields({
  scope,
  types,
  onScope,
  onTypes,
}: {
  scope: ApplicabilityScope;
  types: string[];
  onScope: (scope: ApplicabilityScope) => void;
  onTypes: (types: string[]) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      <FormField label={t("rules.field.scope")} hint={t("rules.applicabilityHint")}>
        <Select value={scope} onChange={(event) => onScope(event.target.value as ApplicabilityScope)}>
          {MANUAL_SCOPES.map((value) => (
            <option key={value} value={value}>
              {t(`scope.${value}`)}
            </option>
          ))}
        </Select>
      </FormField>
      {scope === "typed" && <TypeChecklist label={t("rules.field.types")} value={types} onChange={onTypes} />}
    </div>
  );
}

function ApplicabilityForm({ rule }: { rule: Rule }) {
  const { t, tOptional, formatNumber } = useI18n();
  const { typeName } = useDocumentTypes();
  const queryClient = useQueryClient();
  const initialScope = (MANUAL_SCOPES as readonly string[]).includes(rule.applicability_scope)
    ? (rule.applicability_scope as ApplicabilityScope)
    : "typed";
  const [scope, setScope] = useState<ApplicabilityScope>(initialScope);
  const [types, setTypes] = useState<string[]>(rule.document_types ?? []);
  const save = useMutation({
    mutationFn: () => api.rules.setApplicability(rule.id, scope, scope === "typed" ? types : []),
    onSettled: () => invalidateCatalog(queryClient),
  });
  const automatic = rule.automatic_applicability as
    | { scope?: string; document_types?: string[]; confidence?: number }
    | null
    | undefined;

  return (
    <Panel title={t("rules.applicability")}>
      <p className="text-sm">
        {tOptional(`scope.${rule.applicability_scope}`) ?? rule.applicability_scope}
        {(rule.document_types ?? []).length > 0 && `: ${(rule.document_types ?? []).map(typeName).join(", ")}`}
      </p>
      {automatic?.scope && (
        <p className="text-sm text-muted-foreground">
          {t("rules.automatic", {
            scope: tOptional(`scope.${automatic.scope}`) ?? automatic.scope,
            types: automatic.document_types?.length ? ` (${automatic.document_types.map(typeName).join(", ")})` : "",
            confidence:
              typeof automatic.confidence === "number"
                ? formatNumber(automatic.confidence, { style: "percent", maximumFractionDigits: 0 })
                : t("common.none"),
          })}
        </p>
      )}
      {rule.applicability_source === "manual" && <p className="text-sm text-muted-foreground">{t("rules.source.manual")}</p>}
      <fieldset disabled={save.isPending} className="space-y-3">
        <ScopeFields scope={scope} types={types} onScope={setScope} onTypes={setTypes} />
        <Button variant="outline" onClick={() => save.mutate()} disabled={scope === "typed" && types.length === 0}>
          {t("rules.saveApplicability")}
        </Button>
      </fieldset>
      {save.isSuccess && <p role="status" className="text-sm text-success">{t("action.saved")}</p>}
      {save.isError && <ErrorAlert error={save.error} showServerMessage />}
    </Panel>
  );
}
