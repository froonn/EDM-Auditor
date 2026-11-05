import { keepPreviousData, useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, type RuleFilters } from "@/api/endpoints";
import { CHECK_TYPES, type ApplicabilityScope, type Rule } from "@/api/types";
import { SeverityBadge } from "@/components/badges";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { FormField, Select } from "@/components/ui/form";
import { invalidateCatalog, queryKeys, useDocumentTypes } from "@/features/queries";
import { useI18n } from "@/i18n";

const PAGE_SIZE = 20;
const TOGGLE_KEY = ["toggleRule"];

interface RuleToggle {
  id: number;
  name: string;
  isActive: boolean;
}
const SCOPES: ApplicabilityScope[] = ["universal", "typed", "manual_only", "unknown"];

export function RulesPage() {
  const { t, tOptional } = useI18n();
  const types = useDocumentTypes();
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<RuleFilters>({});

  const acts = useQuery({ queryKey: queryKeys.legalActs, queryFn: ({ signal }) => api.legalActs.all(signal) });
  const actCodes = new Map((acts.data ?? []).map((act) => [act.id, act.code]));
  const request = { limit: PAGE_SIZE, offset, ...filters };
  const rules = useQuery({
    queryKey: queryKeys.rulePage(request),
    queryFn: ({ signal }) => api.rules.list(request, signal),
    placeholderData: keepPreviousData,
  });
  // Several rules can be switched at once. One mutation object remembers only its latest call, so
  // the pending switches are read from the mutation cache instead.
  const [failures, setFailures] = useState<ReadonlyMap<number, { name: string; error: unknown }>>(() => new Map());
  const toggle = useMutation({
    mutationKey: TOGGLE_KEY,
    mutationFn: (change: RuleToggle) => api.rules.update(change.id, { is_active: change.isActive }),
    onError: (error, change) => setFailures((current) => new Map(current).set(change.id, { name: change.name, error })),
    // Returning the promise keeps the switch pending until the list shows the new state.
    onSettled: () => invalidateCatalog(queryClient),
  });
  const pending = new Map(
    useMutationState({
      filters: { mutationKey: TOGGLE_KEY, status: "pending" },
      select: (mutation) => mutation.state.variables as RuleToggle,
    }).map((change) => [change.id, change.isActive]),
  );
  const switchRule = (rule: Rule) => {
    setFailures((current) => {
      const next = new Map(current);
      next.delete(rule.id);
      return next;
    });
    toggle.mutate({ id: rule.id, name: rule.name, isActive: !rule.is_active });
  };

  const filter = (changes: RuleFilters) => {
    setFilters((current) => ({ ...current, ...changes }));
    setOffset(0);
  };

  const columns: Column<Rule>[] = [
    { key: "severity", header: t("rules.column.severity"), className: "w-32", cell: (rule) => <SeverityBadge severity={rule.severity} /> },
    {
      key: "rule",
      header: t("rules.column.rule"),
      cell: (rule) => (
        <div>
          <Link to={`/rules/${rule.id}`} className="font-medium text-primary hover:underline">
            {rule.name}
          </Link>
          <p className="font-mono text-xs text-muted-foreground">{rule.rule_code}</p>
        </div>
      ),
    },
    { key: "check", header: t("rules.column.check"), cell: (rule) => tOptional(`rules.check.${rule.check_type}`) ?? rule.check_type },
    {
      key: "act",
      header: t("rules.column.act"),
      cell: (rule) => (rule.legal_act_id ? (actCodes.get(rule.legal_act_id) ?? `#${rule.legal_act_id}`) : t("common.none")),
    },
    {
      key: "scope",
      header: t("rules.column.scope"),
      cell: (rule) => (
        <div>
          {tOptional(`scope.${rule.applicability_scope}`) ?? rule.applicability_scope}
          {(rule.document_types ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">{(rule.document_types ?? []).map(types.typeName).join(", ")}</p>
          )}
        </div>
      ),
    },
    {
      key: "active",
      header: t("rules.column.active"),
      className: "w-0",
      cell: (rule) => (
        <input
          type="checkbox"
          aria-label={t("rules.toggle", { name: rule.name })}
          // A pending switch shows the requested state and waits: the server rebuilds the search index
          // before it answers, and the list is read again after that.
          checked={pending.get(rule.id) ?? rule.is_active}
          disabled={pending.has(rule.id)}
          onChange={() => switchRule(rule)}
        />
      ),
    },
  ];

  return (
    <section className="space-y-4">
      <div className="flex items-start gap-4">
        <div className="flex-1 space-y-1">
          <h1 className="text-2xl font-semibold">{t("rules.title")}</h1>
          <p className="max-w-4xl text-muted-foreground">{t("rules.description")}</p>
        </div>
        <Button asChild>
          <Link to="/rules/new">
            <Plus aria-hidden />
            {t("rules.new")}
          </Link>
        </Button>
      </div>
      <div className="grid grid-cols-4 gap-3">
        <FormField label={t("rules.filter.active")}>
          <Select
            value={filters.is_active === undefined ? "" : String(filters.is_active)}
            onChange={(event) => filter({ is_active: event.target.value === "" ? undefined : event.target.value === "true" })}
          >
            <option value="">{t("common.all")}</option>
            <option value="true">{t("rules.filter.activeOnly")}</option>
            <option value="false">{t("rules.filter.inactiveOnly")}</option>
          </Select>
        </FormField>
        <FormField label={t("rules.filter.type")}>
          <Select value={filters.document_type ?? ""} onChange={(event) => filter({ document_type: event.target.value || undefined })}>
            <option value="">{t("common.all")}</option>
            {(types.data ?? []).map((type) => (
              <option key={type.code} value={type.code}>
                {type.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={t("rules.filter.check")}>
          <Select value={filters.check_type ?? ""} onChange={(event) => filter({ check_type: event.target.value || undefined })}>
            <option value="">{t("common.all")}</option>
            {CHECK_TYPES.map((check) => (
              <option key={check} value={check}>
                {t(`rules.check.${check}`)}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={t("rules.filter.scope")}>
          <Select
            value={filters.applicability_scope ?? ""}
            onChange={(event) => filter({ applicability_scope: (event.target.value || undefined) as ApplicabilityScope | undefined })}
          >
            <option value="">{t("common.all")}</option>
            {SCOPES.map((scope) => (
              <option key={scope} value={scope}>
                {t(`scope.${scope}`)}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
      {[...failures].map(([id, failure]) => (
        <div key={id} className="space-y-1">
          <p className="text-sm font-medium">{t("rules.toggleFailed", { name: failure.name })}</p>
          <ErrorAlert error={failure.error} showServerMessage />
        </div>
      ))}
      {rules.isError ? (
        <ErrorAlert error={rules.error} onRetry={() => void rules.refetch()} retrying={rules.isFetching} />
      ) : (
        <DataTable
          columns={columns}
          rows={rules.data?.items}
          rowKey={(rule) => rule.id}
          isLoading={rules.isPending}
          emptyText={t("rules.empty")}
          pagination={rules.data && { limit: PAGE_SIZE, offset, total: rules.data.total, onOffsetChange: setOffset }}
        />
      )}
    </section>
  );
}
