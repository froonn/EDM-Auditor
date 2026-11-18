import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { hasErrorCode } from "@/api/client";
import { api } from "@/api/endpoints";
import {
  MANUAL_SCOPES,
  SEVERITIES,
  type ApplicabilityScope,
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
        <h1 className="flex-1 text-2xl font-semibold">{rule ? (rule.subject ?? rule.name ?? "") : t("rules.createTitle")}</h1>
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
          title={t("rules.deleteTitle", { name: rule.subject ?? rule.name ?? "" })}
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

function RuleForm({ rule }: { rule: Rule | null }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const acts = useQuery({ queryKey: queryKeys.legalActs, queryFn: ({ signal }) => api.legalActs.all(signal) });

  const [code, setCode] = useState("");
  const [subject, setSubject] = useState(rule?.subject ?? rule?.name ?? "");
  const [constraintText, setConstraintText] = useState(rule?.constraint_text ?? rule?.description ?? "");
  const [condition, setCondition] = useState(rule?.condition ?? "");
  const [constraintJson, setConstraintJson] = useState(
    rule?.constraint_json ? JSON.stringify(rule.constraint_json, null, 2) : "",
  );
  const [severity, setSeverity] = useState(rule?.severity ?? "medium");
  const [active, setActive] = useState(rule?.is_active ?? true);
  const [actId, setActId] = useState("");
  const [scope, setScope] = useState<ApplicabilityScope>("universal");
  const [types, setTypes] = useState<string[]>([]);
  const [numberError, setNumberError] = useState(false);

  const save = useMutation({
    mutationFn: async () => {
      const parsedConstraint = constraintJson.trim() ? JSON.parse(constraintJson) : null;
      if (rule) {
        return api.rules.update(rule.id, {
          subject: subject.trim(),
          constraint_text: constraintText.trim(),
          constraint_json: parsedConstraint,
          condition: condition.trim(),
          severity,
          is_active: active,
        });
      }
      return api.rules.create({
        rule_code: code.trim(),
        subject: subject.trim(),
        constraint_text: constraintText.trim(),
        constraint_json: parsedConstraint,
        condition: condition.trim(),
        severity,
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
    setNumberError(false);
    if (constraintJson.trim()) {
      try {
        const parsed = JSON.parse(constraintJson);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          setNumberError(true);
          return;
        }
      } catch {
        setNumberError(true);
        return;
      }
    }
    save.mutate();
  };
  const valid = subject.trim() && constraintText.trim() && (rule || code.trim()) && (rule || scope !== "typed" || types.length > 0);

  return (
    <Panel title={t("rules.editTitle")}>
      <fieldset disabled={save.isPending} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          {!rule && (
            <FormField label={t("rules.field.code")} hint={t("rules.field.codeHint")}>
              <Input value={code} onChange={(event) => setCode(event.target.value)} maxLength={100} />
            </FormField>
          )}
          <FormField label={t("rules.field.subject")} className={rule ? "col-span-2" : undefined}>
            <Input value={subject} onChange={(event) => setSubject(event.target.value)} maxLength={255} />
          </FormField>
          <FormField label={t("rules.field.constraintText")} className="col-span-2">
            <Textarea value={constraintText} onChange={(event) => setConstraintText(event.target.value)} rows={3} />
          </FormField>
          <FormField label={t("rules.field.condition")} className="col-span-2">
            <Textarea value={condition} onChange={(event) => setCondition(event.target.value)} rows={2} />
          </FormField>
          <FormField label={t("rules.field.constraintJson")} className="col-span-2">
            <Textarea value={constraintJson} onChange={(event) => setConstraintJson(event.target.value)} rows={4} />
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
        </div>

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
          {MANUAL_SCOPES.map((value) => <option key={value} value={value}>{t(`scope.${value}`)}</option>)}
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
