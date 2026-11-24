import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "@/api/endpoints";
import type { GroupItem, PermissionInfo } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel } from "@/components/ui/form";
import { queryKeys } from "@/features/queries";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

export function GroupsPage() {
  const { t } = useI18n();
  const { session, refreshSession } = useAuth();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<"custom" | "personal">("custom");
  const [personalSearch, setPersonalSearch] = useState("");
  const [deleting, setDeleting] = useState<GroupItem | null>(null);

  const isSuperAdmin = Boolean(session.user?.isSuperAdmin);
  const actorPerms: ReadonlySet<string> = session.permissions;

  const permissionsQuery = useQuery({
    queryKey: queryKeys.permissionsCatalog,
    queryFn: ({ signal }) => api.permissions.list(signal),
  });
  const customGroupsQuery = useQuery({
    queryKey: queryKeys.groups("custom"),
    queryFn: ({ signal }) => api.groups.list({ kind: "custom" }, signal),
  });
  const personalGroupsQuery = useQuery({
    queryKey: queryKeys.groups("personal"),
    queryFn: ({ signal }) => api.groups.list({ kind: "personal" }, signal),
  });

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.allGroups });
    void queryClient.invalidateQueries({ queryKey: queryKeys.allUsers });
    void refreshSession();
  };

  const removeGroup = useMutation({
    mutationFn: (id: number) => api.groups.remove(id),
    onSuccess: () => {
      setDeleting(null);
      invalidateAll();
    },
  });

  const catalog = permissionsQuery.data ?? [];
  const filteredPersonal = (personalGroupsQuery.data ?? []).filter((g) => {
    const q = personalSearch.trim().toLowerCase();
    return !q || g.name.toLowerCase().includes(q) || (g.owner_username ?? "").toLowerCase().includes(q);
  });

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("groups.title")}</h1>
        <p className="max-w-4xl text-muted-foreground">{t("groups.description")}</p>
      </div>

      <div role="tablist" className="flex gap-2 border-b">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "custom"}
          onClick={() => setTab("custom")}
          className={cn(
            "border-b-2 px-4 py-2 text-sm font-medium",
            tab === "custom"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {t("groups.tab.custom")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "personal"}
          onClick={() => setTab("personal")}
          className={cn(
            "border-b-2 px-4 py-2 text-sm font-medium",
            tab === "personal"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {t("groups.tab.personal")}
        </button>
      </div>

      {removeGroup.isError && <ErrorAlert error={removeGroup.error} />}

      {tab === "custom" ? (
        <div className="space-y-4">
          <CreateGroupPanel
            catalog={catalog}
            isSuperAdmin={isSuperAdmin}
            actorPerms={actorPerms}
            onCreated={invalidateAll}
          />
          {customGroupsQuery.isPending && <p role="status">{t("table.loading")}</p>}
          {customGroupsQuery.isError && (
            <ErrorAlert error={customGroupsQuery.error} onRetry={() => void customGroupsQuery.refetch()} />
          )}
          {customGroupsQuery.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("groups.empty")}</p>
          )}
          <div className="space-y-4">
            {customGroupsQuery.data?.map((group) => (
              <GroupCard
                key={group.id}
                group={group}
                catalog={catalog}
                isSuperAdmin={isSuperAdmin}
                actorPerms={actorPerms}
                onSaved={invalidateAll}
                onDelete={() => setDeleting(group)}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">{t("groups.personalHint")}</p>
          <FormField label={t("groups.searchPersonal")} className="w-72">
            <Input
              type="search"
              value={personalSearch}
              onChange={(e) => setPersonalSearch(e.target.value)}
            />
          </FormField>
          {personalGroupsQuery.isPending && <p role="status">{t("table.loading")}</p>}
          {personalGroupsQuery.isError && (
            <ErrorAlert error={personalGroupsQuery.error} onRetry={() => void personalGroupsQuery.refetch()} />
          )}
          {filteredPersonal.length === 0 && !personalGroupsQuery.isPending && (
            <p className="text-sm text-muted-foreground">{t("groups.empty")}</p>
          )}
          <div className="space-y-4">
            {filteredPersonal.map((group) => (
              <GroupCard
                key={group.id}
                group={group}
                catalog={catalog}
                isSuperAdmin={isSuperAdmin}
                actorPerms={actorPerms}
                onSaved={invalidateAll}
              />
            ))}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("groups.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("groups.deleteDescription")}
        confirmLabel={t("action.delete")}
        destructive
        onConfirm={() => deleting && removeGroup.mutate(deleting.id)}
      />
    </section>
  );
}

function canTogglePermission(
  info: PermissionInfo,
  isSuperAdmin: boolean,
  actorPerms: ReadonlySet<string>,
): boolean {
  if (isSuperAdmin) return true;
  if (info.super_admin_only) return false;
  return actorPerms.has(info.code);
}

const GROUP_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$/;

function CreateGroupPanel({
  catalog,
  isSuperAdmin,
  actorPerms,
  onCreated,
}: {
  catalog: PermissionInfo[];
  isSuperAdmin: boolean;
  actorPerms: ReadonlySet<string>;
  onCreated: () => void;
}) {
  const { t, tOptional } = useI18n();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [nameTouched, setNameTouched] = useState(false);

  function validateGroupName(value: string): string | undefined {
    const clean = value.trim();
    if (!clean) return t("validation.required");
    if (!GROUP_NAME_RE.test(clean)) return t("groups.validation.name");
    if (clean.toLowerCase() === "super-admin") return t("groups.validation.reserved");
    return undefined;
  }

  const nameError = nameTouched ? validateGroupName(name) : undefined;

  const create = useMutation({
    mutationFn: () =>
      api.groups.create({
        name: name.trim(),
        description: description.trim(),
        permissions: selected,
      }),
    onSuccess: () => {
      setName("");
      setDescription("");
      setSelected([]);
      setNameTouched(false);
      onCreated();
    },
  });

  function toggle(code: string) {
    setSelected((curr) => (curr.includes(code) ? curr.filter((x) => x !== code) : [...curr, code]));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setNameTouched(true);
    if (validateGroupName(name)) return;
    create.mutate();
  }

  return (
    <Panel title={t("groups.createTitle")}>
      <form onSubmit={handleSubmit} noValidate className="space-y-3">
        <fieldset disabled={create.isPending} className="space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <FormField label={t("groups.field.name")} hint={t("groups.field.nameHint")} error={nameError}>
              <Input
                value={name}
                aria-invalid={Boolean(nameError)}
                className={nameError ? "border-destructive" : undefined}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => setNameTouched(true)}
                maxLength={100}
                required
              />
            </FormField>
            <FormField label={t("groups.field.description")}>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} />
            </FormField>
          </div>
          {catalog.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {catalog.map((info) => {
                const allowed = canTogglePermission(info, isSuperAdmin, actorPerms);
                return (
                  <label
                    key={info.code}
                    className={cn("flex items-start gap-2 text-sm", !allowed && "opacity-50")}
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={selected.includes(info.code)}
                      disabled={!allowed}
                      onChange={() => toggle(info.code)}
                    />
                    <span>
                      {tOptional(`perm.${info.code}`) ?? info.description}
                      {info.super_admin_only && (
                        <Badge className="ml-1.5 bg-muted text-[10px] font-normal">
                          {t("groups.superAdminOnlyHint")}
                        </Badge>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
          <Button type="submit">{t("action.create")}</Button>
        </fieldset>
        {create.isError && <ErrorAlert error={create.error} />}
      </form>
    </Panel>
  );
}

function GroupCard({
  group,
  catalog,
  isSuperAdmin,
  actorPerms,
  onSaved,
  onDelete,
}: {
  group: GroupItem;
  catalog: PermissionInfo[];
  isSuperAdmin: boolean;
  actorPerms: ReadonlySet<string>;
  onSaved: () => void;
  onDelete?: () => void;
}) {
  const { t, tOptional } = useI18n();
  const [selected, setSelected] = useState<string[]>(() => [...(group.permissions ?? [])]);

  const save = useMutation({
    mutationFn: () => api.groups.setPermissions(group.id, selected),
    onSuccess: onSaved,
  });

  const original = [...(group.permissions ?? [])].sort().join(",");
  const dirty = [...selected].sort().join(",") !== original;
  const memberCount = group.member_count ?? 0;

  function toggle(code: string) {
    setSelected((curr) => (curr.includes(code) ? curr.filter((x) => x !== code) : [...curr, code]));
  }

  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold">{group.name}</h3>
            <Badge className="bg-muted text-xs text-muted-foreground">
              {t("groups.members", { count: memberCount })}
            </Badge>
          </div>
          {group.description && <p className="text-sm text-muted-foreground">{group.description}</p>}
          {group.kind === "custom" && (
            <p className="text-xs text-muted-foreground">
              {(group.members ?? []).length > 0
                ? (group.members ?? []).map((m) => m.username).join(", ")
                : t("groups.noMembers")}
            </p>
          )}
        </div>

        {onDelete && group.kind === "custom" && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive"
            disabled={memberCount > 0}
            title={memberCount > 0 ? t("groups.deleteEmptyOnly") : undefined}
            onClick={onDelete}
          >
            <Trash2 aria-hidden className="size-4" />
            {t("action.delete")}
          </Button>
        )}
      </div>

      <div className="space-y-2 border-t pt-3">
        <p className="text-xs font-medium text-muted-foreground">{t("groups.permissionsTitle")}</p>
        <div className="grid grid-cols-2 gap-2">
          {catalog.map((info) => {
            const allowed = canTogglePermission(info, isSuperAdmin, actorPerms);
            return (
              <label
                key={info.code}
                className={cn("flex items-start gap-2 text-sm", !allowed && "opacity-50")}
              >
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={selected.includes(info.code)}
                  disabled={!allowed || save.isPending}
                  onChange={() => toggle(info.code)}
                />
                <span>
                  {tOptional(`perm.${info.code}`) ?? info.description}
                  {info.super_admin_only && (
                    <Badge className="ml-1.5 bg-muted text-[10px] font-normal">
                      {t("groups.superAdminOnlyHint")}
                    </Badge>
                  )}
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="button" size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          {t("groups.savePermissions")}
        </Button>
        {save.isSuccess && (
          <span role="status" className="text-sm text-success">
            {t("action.saved")}
          </span>
        )}
      </div>
      {save.isError && <ErrorAlert error={save.error} />}
    </Panel>
  );
}
