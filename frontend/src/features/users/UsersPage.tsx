import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, ShieldCheck, Users, X } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { api } from "@/api/endpoints";
import type { AuthAuditLogItem, GroupItem, UserItem } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { isPermission } from "@/auth/permissions";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorAlert } from "@/components/ErrorAlert";
import { PasswordInput, TemporaryPasswordField } from "@/components/PasswordInput";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel, Select } from "@/components/ui/form";
import { queryKeys } from "@/features/queries";
import { useI18n } from "@/i18n";
import { generateTemporaryPassword } from "@/lib/password";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

export function UsersPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"list" | "auditLog">("list");

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("users.title")}</h1>
        <p className="text-muted-foreground">{t("users.description")}</p>
      </div>

      <div role="tablist" className="flex gap-2 border-b">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "list"}
          onClick={() => setTab("list")}
          className={cn(
            "border-b-2 px-4 py-2 text-sm font-medium",
            tab === "list"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {t("users.tab.list")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "auditLog"}
          onClick={() => setTab("auditLog")}
          className={cn(
            "border-b-2 px-4 py-2 text-sm font-medium",
            tab === "auditLog"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {t("users.tab.auditLog")}
        </button>
      </div>

      {tab === "list" ? <UsersListTab /> : <SecurityAuditLogTab />}
    </section>
  );
}

function canAssignGroup(group: GroupItem, isSuperAdmin: boolean, actorPermissions: ReadonlySet<string>): boolean {
  if (isSuperAdmin) return true;
  const perms = group.permissions ?? [];
  if (perms.includes("groups.manage")) return false;
  return perms.every((perm) => actorPermissions.has(perm));
}

function UsersListTab() {
  const { t, tOptional, formatDateTime } = useI18n();
  const { session, refreshSession } = useAuth();
  const queryClient = useQueryClient();

  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<string>("");
  const [statusNotice, setStatusNotice] = useState<string | null>(null);

  const [editingGroupsUser, setEditingGroupsUser] = useState<UserItem | null>(null);
  const [resetPasswordUser, setResetPasswordUser] = useState<UserItem | null>(null);
  const [transferUser, setTransferUser] = useState<UserItem | null>(null);
  const [issuedPassword, setIssuedPassword] = useState<{
    kind: "created" | "reset";
    username: string;
    password: string;
  } | null>(null);

  const isSuperAdmin = Boolean(session.user?.isSuperAdmin);
  const actorPerms: ReadonlySet<string> = session.permissions;

  const request = {
    limit: PAGE_SIZE,
    offset,
    search: search.trim() || undefined,
    is_active: activeFilter === "" ? undefined : activeFilter === "true",
  };
  const usersQuery = useQuery({
    queryKey: queryKeys.users(request),
    queryFn: ({ signal }) => api.users.list(request, signal),
    placeholderData: keepPreviousData,
  });
  const customGroupsQuery = useQuery({
    queryKey: queryKeys.groups("custom"),
    queryFn: ({ signal }) => api.groups.list({ kind: "custom" }, signal),
  });

  const invalidateUsers = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.allUsers });
    void queryClient.invalidateQueries({ queryKey: queryKeys.allGroups });
  };

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => api.users.update(id, { is_active }),
    onSettled: invalidateUsers,
  });

  const revokeSessions = useMutation({
    mutationFn: (id: number) => api.users.revokeSessions(id),
    onSuccess: (res) => {
      setStatusNotice(t("users.sessionsRevoked", { count: res.revoked_count }));
    },
  });

  const columns: Column<UserItem>[] = [
    {
      key: "user",
      header: t("users.column.user"),
      cell: (u) => (
        <div>
          <div className="flex items-center gap-1.5">
            <span className="font-medium">{u.full_name || u.username}</span>
            {u.is_super_admin && (
              <Badge className="gap-1 bg-primary text-primary-foreground">
                <ShieldCheck aria-hidden className="size-3" />
                {t("auth.superAdminBadge")}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            <span className="font-mono">{u.username}</span> · {u.email}
          </p>
        </div>
      ),
    },
    {
      key: "groups",
      header: t("users.column.groups"),
      cell: (u) => {
        const groups = u.custom_groups ?? [];
        if (groups.length === 0) return <span className="text-muted-foreground">{t("common.none")}</span>;
        return (
          <div className="flex flex-wrap gap-1">
            {groups.map((g) => (
              <Badge key={g.id} className="bg-muted text-muted-foreground">
                {g.name}
              </Badge>
            ))}
          </div>
        );
      },
    },
    {
      key: "status",
      header: t("users.column.status"),
      cell: (u) => (
        <div className="flex flex-col items-start gap-1">
          {u.is_active ? (
            <Badge className="border-success/30 bg-success-muted text-success">{t("users.active")}</Badge>
          ) : (
            <Badge className="bg-muted text-muted-foreground">{t("users.disabled")}</Badge>
          )}
          {u.must_change_password && (
            <span className="text-xs text-warning-foreground">{t("users.mustChangePassword")}</span>
          )}
        </div>
      ),
    },
    {
      key: "lastLogin",
      header: t("users.column.lastLogin"),
      cell: (u) => (u.last_login_at ? formatDateTime(u.last_login_at) : t("common.none")),
      className: "whitespace-nowrap",
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("users.column.actions")}</span>,
      className: "w-0 whitespace-nowrap",
      cell: (u) => {
        const isSelf = session.user?.id === u.id;
        const canModify = isSuperAdmin || !u.is_super_admin;
        return (
          <div className="flex flex-wrap gap-1">
            {canModify && (
              <Button size="sm" variant="outline" onClick={() => setEditingGroupsUser(u)}>
                <Users aria-hidden className="size-3.5" />
                {t("users.manageGroups")}
              </Button>
            )}
            {canModify && (
              <Button size="sm" variant="ghost" onClick={() => setResetPasswordUser(u)}>
                <KeyRound aria-hidden className="size-3.5" />
                {t("users.resetPassword")}
              </Button>
            )}
            {canModify && (
              <Button
                size="sm"
                variant="ghost"
                disabled={revokeSessions.isPending}
                onClick={() => revokeSessions.mutate(u.id)}
              >
                <LogOut aria-hidden className="size-3.5" />
                {t("users.revokeSessions")}
              </Button>
            )}
            {canModify && !u.is_super_admin && !isSelf && (
              <Button
                size="sm"
                variant="ghost"
                className={u.is_active ? "text-destructive" : undefined}
                disabled={toggleActive.isPending}
                onClick={() => toggleActive.mutate({ id: u.id, is_active: !u.is_active })}
              >
                {u.is_active ? t("users.disable") : t("users.enable")}
              </Button>
            )}
            {isSuperAdmin && !u.is_super_admin && u.is_active && (
              <Button size="sm" variant="outline" onClick={() => setTransferUser(u)}>
                <ShieldCheck aria-hidden className="size-3.5" />
                {t("users.transferSuperAdmin")}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      <CreateUserPanel
        customGroups={customGroupsQuery.data ?? []}
        isSuperAdmin={isSuperAdmin}
        actorPerms={actorPerms}
        onCreated={(issued) => {
          invalidateUsers();
          setIssuedPassword({ kind: "created", ...issued });
        }}
      />

      {issuedPassword && (
        <IssuedPasswordBanner issued={issuedPassword} onDismiss={() => setIssuedPassword(null)} />
      )}

      <div className="flex flex-wrap items-end gap-3">
        <FormField label={t("action.search")} className="w-72">
          <Input
            type="search"
            value={search}
            placeholder={t("users.searchPlaceholder")}
            onChange={(event) => {
              setSearch(event.target.value);
              setOffset(0);
            }}
          />
        </FormField>
        <FormField label={t("users.filter.status")} className="w-56">
          <Select
            value={activeFilter}
            onChange={(event) => {
              setActiveFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">{t("common.all")}</option>
            <option value="true">{t("users.filter.active")}</option>
            <option value="false">{t("users.filter.disabled")}</option>
          </Select>
        </FormField>
      </div>

      {statusNotice && (
        <p role="status" className="text-sm text-success">
          {statusNotice}
        </p>
      )}
      {toggleActive.isError && <ErrorAlert error={toggleActive.error} />}
      {revokeSessions.isError && <ErrorAlert error={revokeSessions.error} />}

      {usersQuery.isError ? (
        <ErrorAlert error={usersQuery.error} onRetry={() => void usersQuery.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={usersQuery.data?.items}
          rowKey={(u) => u.id}
          isLoading={usersQuery.isPending}
          emptyText={t("users.empty")}
          pagination={
            usersQuery.data && { limit: PAGE_SIZE, offset, total: usersQuery.data.total, onOffsetChange: setOffset }
          }
        />
      )}

      {editingGroupsUser && (
        <UserGroupsDialog
          user={editingGroupsUser}
          customGroups={customGroupsQuery.data ?? []}
          isSuperAdmin={isSuperAdmin}
          actorPerms={actorPerms}
          onClose={() => setEditingGroupsUser(null)}
          onSaved={() => {
            invalidateUsers();
            void refreshSession();
            setEditingGroupsUser(null);
          }}
          tOptional={tOptional}
        />
      )}

      {resetPasswordUser && (
        <ResetPasswordDialog
          user={resetPasswordUser}
          onClose={() => setResetPasswordUser(null)}
          onSaved={(password) => {
            invalidateUsers();
            setIssuedPassword({ kind: "reset", username: resetPasswordUser.username, password });
            setResetPasswordUser(null);
          }}
        />
      )}

      {transferUser && (
        <TransferSuperAdminDialog
          user={transferUser}
          onClose={() => setTransferUser(null)}
          onTransferred={(username) => {
            invalidateUsers();
            void refreshSession();
            setTransferUser(null);
            setStatusNotice(t("users.transferSuccess", { username }));
          }}
        />
      )}
    </div>
  );
}

function IssuedPasswordBanner({
  issued,
  onDismiss,
}: {
  issued: { kind: "created" | "reset"; username: string; password: string };
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  const fieldId = useId();
  const message =
    issued.kind === "created"
      ? t("users.issuedPasswordCreated", { username: issued.username })
      : t("users.issuedPasswordReset", { username: issued.username });

  return (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-success/40 bg-success-muted/40 p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">{message}</p>
        <Button type="button" variant="ghost" size="sm" aria-label={t("action.close")} onClick={onDismiss}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <TemporaryPasswordField id={fieldId} value={issued.password} />
    </div>
  );
}

function CreateUserPanel({
  customGroups,
  isSuperAdmin,
  actorPerms,
  onCreated,
}: {
  customGroups: GroupItem[];
  isSuperAdmin: boolean;
  actorPerms: ReadonlySet<string>;
  onCreated: (issued: { username: string; password: string }) => void;
}) {
  const { t } = useI18n();
  const passwordId = useId();
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState(() => generateTemporaryPassword());
  const [mustChange, setMustChange] = useState(true);
  const [selectedGroupIds, setSelectedGroupIds] = useState<number[]>([]);

  const create = useMutation({
    mutationFn: (payload: {
      username: string;
      email: string;
      password: string;
      full_name: string;
      custom_group_ids: number[];
      must_change_password: boolean;
    }) => api.users.create(payload),
    onSuccess: (_data, payload) => {
      setUsername("");
      setFullName("");
      setEmail("");
      setPassword(generateTemporaryPassword());
      setSelectedGroupIds([]);
      setMustChange(true);
      onCreated({ username: payload.username, password: payload.password });
    },
  });

  function toggleGroup(id: number) {
    setSelectedGroupIds((curr) => (curr.includes(id) ? curr.filter((x) => x !== id) : [...curr, id]));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate({
      username: username.trim(),
      email: email.trim(),
      password,
      full_name: fullName.trim(),
      custom_group_ids: selectedGroupIds,
      must_change_password: mustChange,
    });
  }

  const ready = username.trim().length >= 2 && email.includes("@") && password.length >= 8;

  return (
    <Panel title={t("users.createTitle")}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <fieldset disabled={create.isPending} className="space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <FormField label={t("users.field.username")} hint={t("users.field.usernameHint")}>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} maxLength={100} required />
            </FormField>
            <FormField label={t("users.field.fullName")}>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={255} />
            </FormField>
            <FormField label={t("users.field.email")}>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={255} required />
            </FormField>
          </div>

          <FormField htmlFor={passwordId} label={t("users.field.password")} hint={t("users.field.passwordHint")}>
            <TemporaryPasswordField
              id={passwordId}
              value={password}
              onRegenerate={() => setPassword(generateTemporaryPassword())}
              disabled={create.isPending}
            />
          </FormField>

          <div className="space-y-1.5">
            <span className="text-sm font-medium">{t("users.field.groups")}</span>
            <div className="flex flex-wrap gap-3">
              {customGroups.map((group) => {
                const allowed = canAssignGroup(group, isSuperAdmin, actorPerms);
                return (
                  <label
                    key={group.id}
                    title={allowed ? undefined : t("users.groupCeilingHint")}
                    className={cn("flex items-center gap-1.5 text-sm", !allowed && "opacity-50")}
                  >
                    <input
                      type="checkbox"
                      checked={selectedGroupIds.includes(group.id)}
                      disabled={!allowed}
                      onChange={() => toggleGroup(group.id)}
                    />
                    <span>{group.name}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
            {t("users.field.mustChangePassword")}
          </label>

          <Button type="submit" disabled={!ready}>
            {t("action.create")}
          </Button>
        </fieldset>
        {create.isError && <ErrorAlert error={create.error} />}
      </form>
    </Panel>
  );
}

function UserGroupsDialog({
  user,
  customGroups,
  isSuperAdmin,
  actorPerms,
  onClose,
  onSaved,
  tOptional,
}: {
  user: UserItem;
  customGroups: GroupItem[];
  isSuperAdmin: boolean;
  actorPerms: ReadonlySet<string>;
  onClose: () => void;
  onSaved: () => void;
  tOptional: (key: string) => string | undefined;
}) {
  const { t } = useI18n();
  const [selectedIds, setSelectedIds] = useState<number[]>(() => (user.custom_groups ?? []).map((g) => g.id));

  const save = useMutation({
    mutationFn: () => api.users.setGroups(user.id, selectedIds),
    onSuccess: onSaved,
  });

  function toggle(id: number) {
    setSelectedIds((curr) => (curr.includes(id) ? curr.filter((x) => x !== id) : [...curr, id]));
  }

  // Preview effective permissions (union of selected custom groups + user's existing non-custom perms).
  const previewPerms = new Set<string>();
  for (const g of customGroups) {
    if (selectedIds.includes(g.id)) {
      for (const perm of g.permissions ?? []) previewPerms.add(perm);
    }
  }
  const sortedPreview = [...previewPerms].sort();

  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent className="max-w-xl">
        <div className="space-y-1">
          <AlertDialogTitle>{t("users.manageGroupsTitle", { username: user.username })}</AlertDialogTitle>
          <AlertDialogDescription>{user.full_name || user.email}</AlertDialogDescription>
        </div>

        <div className="space-y-3">
          <div className="space-y-2">
            {customGroups.map((group) => {
              const allowed = canAssignGroup(group, isSuperAdmin, actorPerms);
              return (
                <label
                  key={group.id}
                  title={allowed ? undefined : t("users.groupCeilingHint")}
                  className={cn(
                    "flex items-start gap-2 rounded-md border p-2 text-sm",
                    !allowed && "opacity-50",
                  )}
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selectedIds.includes(group.id)}
                    disabled={!allowed || save.isPending}
                    onChange={() => toggle(group.id)}
                  />
                  <div>
                    <p className="font-medium">{group.name}</p>
                    {group.description && <p className="text-xs text-muted-foreground">{group.description}</p>}
                  </div>
                </label>
              );
            })}
          </div>

          <div className="space-y-1 rounded-md bg-muted/40 p-3">
            <p className="text-xs font-medium text-muted-foreground">{t("users.effectivePermissions")}</p>
            {sortedPreview.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("users.noPermissions")}</p>
            ) : (
              <div className="flex flex-wrap gap-1">
                {sortedPreview.map((perm) => (
                  <Badge key={perm} className="bg-card text-[11px] font-normal">
                    {isPermission(perm) ? (tOptional(`perm.${perm}`) ?? perm) : perm}
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {save.isError && <ErrorAlert error={save.error} />}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={save.isPending}>
              {t("action.cancel")}
            </Button>
            <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
              {t("action.save")}
            </Button>
          </div>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function ResetPasswordDialog({
  user,
  onClose,
  onSaved,
}: {
  user: UserItem;
  onClose: () => void;
  onSaved: (newPassword: string) => void;
}) {
  const { t } = useI18n();
  const passwordId = useId();
  const [newPassword, setNewPassword] = useState(() => generateTemporaryPassword());
  const reset = useMutation({
    mutationFn: (password: string) => api.users.update(user.id, { new_password: password }),
    onSuccess: (_data, password) => onSaved(password),
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    reset.mutate(newPassword);
  }

  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <div className="space-y-1">
          <AlertDialogTitle>{t("users.resetPasswordTitle", { username: user.username })}</AlertDialogTitle>
          <AlertDialogDescription>{t("users.resetPasswordDescription")}</AlertDialogDescription>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <FormField htmlFor={passwordId} label={t("users.newTempPassword")} hint={t("users.field.passwordHint")}>
            <TemporaryPasswordField
              id={passwordId}
              value={newPassword}
              onRegenerate={() => setNewPassword(generateTemporaryPassword())}
              disabled={reset.isPending}
            />
          </FormField>
          {reset.isError && <ErrorAlert error={reset.error} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={reset.isPending}>
              {t("action.cancel")}
            </Button>
            <Button type="submit" disabled={reset.isPending || newPassword.length < 8}>
              {t("users.resetPassword")}
            </Button>
          </div>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function TransferSuperAdminDialog({
  user,
  onClose,
  onTransferred,
}: {
  user: UserItem;
  onClose: () => void;
  onTransferred: (username: string) => void;
}) {
  const { t } = useI18n();
  const passwordId = useId();
  const [currentPassword, setCurrentPassword] = useState("");
  const transfer = useMutation({
    mutationFn: () => api.auth.transferSuperAdmin(currentPassword, user.id),
    onSuccess: (res) => onTransferred(res.new_super_admin_username),
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    transfer.mutate();
  }

  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <div className="space-y-1">
          <AlertDialogTitle>{t("users.transferTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("users.transferDescription", { username: user.username })}</AlertDialogDescription>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <FormField htmlFor={passwordId} label={t("auth.currentPassword")}>
            <PasswordInput
              id={passwordId}
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              disabled={transfer.isPending}
            />
          </FormField>
          {transfer.isError && <ErrorAlert error={transfer.error} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={transfer.isPending}>
              {t("action.cancel")}
            </Button>
            <Button type="submit" variant="destructive" disabled={transfer.isPending || !currentPassword}>
              {t("action.confirm")}
            </Button>
          </div>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function SecurityAuditLogTab() {
  const { t, formatDateTime } = useI18n();
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");

  const request = {
    limit: PAGE_SIZE,
    offset,
    action: action || undefined,
    actor_username: actor.trim() || undefined,
  };
  const logQuery = useQuery({
    queryKey: queryKeys.authAuditLog(request),
    queryFn: ({ signal }) => api.auth.auditLog(request, signal),
    placeholderData: keepPreviousData,
  });

  const columns: Column<AuthAuditLogItem>[] = [
    {
      key: "time",
      header: t("auditLog.column.time"),
      cell: (row) => formatDateTime(row.created_at),
      className: "whitespace-nowrap",
    },
    {
      key: "actor",
      header: t("auditLog.column.actor"),
      cell: (row) => <span className="font-mono text-xs">{row.actor_username || t("common.none")}</span>,
    },
    {
      key: "action",
      header: t("auditLog.column.action"),
      cell: (row) => <Badge className="bg-muted font-mono text-xs">{row.action}</Badge>,
    },
    {
      key: "target",
      header: t("auditLog.column.target"),
      cell: (row) =>
        row.target_type ? (
          <span className="font-mono text-xs">
            {row.target_type}
            {row.target_id ? `#${row.target_id}` : ""}
          </span>
        ) : (
          t("common.none")
        ),
    },
    {
      key: "details",
      header: t("auditLog.column.details"),
      cell: (row) => (
        <span className="font-mono text-xs text-muted-foreground break-all">
          {row.details && Object.keys(row.details).length > 0 ? JSON.stringify(row.details) : t("common.none")}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <FormField label={t("auditLog.filter.action")} className="w-64">
          <Select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">{t("common.all")}</option>
            <option value="login_success">login_success</option>
            <option value="login_failed">login_failed</option>
            <option value="password_changed">password_changed</option>
            <option value="password_reset">password_reset</option>
            <option value="user_created">user_created</option>
            <option value="user_disabled">user_disabled</option>
            <option value="user_groups_updated">user_groups_updated</option>
            <option value="user_sessions_revoked">user_sessions_revoked</option>
            <option value="group_created">group_created</option>
            <option value="group_permissions_updated">group_permissions_updated</option>
            <option value="group_deleted">group_deleted</option>
            <option value="super_admin_transferred">super_admin_transferred</option>
          </Select>
        </FormField>
        <FormField label={t("auditLog.filter.actor")} className="w-64">
          <Input
            type="search"
            value={actor}
            onChange={(e) => {
              setActor(e.target.value);
              setOffset(0);
            }}
          />
        </FormField>
      </div>

      {logQuery.isError ? (
        <ErrorAlert error={logQuery.error} onRetry={() => void logQuery.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={logQuery.data?.items}
          rowKey={(row) => row.id}
          isLoading={logQuery.isPending}
          emptyText={t("auditLog.empty")}
          pagination={
            logQuery.data && { limit: PAGE_SIZE, offset, total: logQuery.data.total, onOffsetChange: setOffset }
          }
        />
      )}
    </div>
  );
}
