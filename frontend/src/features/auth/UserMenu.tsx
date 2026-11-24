import { KeyRound, LogOut, ShieldCheck } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { api } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthProvider";
import { ErrorAlert } from "@/components/ErrorAlert";
import { PasswordInput } from "@/components/PasswordInput";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form";
import { useI18n } from "@/i18n";

export function UserMenu() {
  const { t } = useI18n();
  const { session, logout, logoutAll, applyAuthUser } = useAuth();
  const navigate = useNavigate();
  const currentId = useId();
  const newId = useId();
  const confirmId = useId();

  const [passwordOpen, setPasswordOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [touched, setTouched] = useState<{ current?: boolean; next?: boolean; confirm?: boolean }>({});
  const [apiError, setApiError] = useState<unknown>(null);
  const [savedMessage, setSavedMessage] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const user = session.user;
  if (!user) return null;

  const customGroups = user.groups.filter((g) => g.kind === "custom");

  const currentError = touched.current && !currentPassword ? t("validation.required") : undefined;
  const newError = touched.next
    ? !newPassword
      ? t("validation.required")
      : newPassword.length < 8
        ? t("auth.passwordTooShort")
        : undefined
    : undefined;
  const confirmError = touched.confirm
    ? !confirmPassword
      ? t("validation.required")
      : confirmPassword !== newPassword
        ? t("auth.passwordMismatch")
        : undefined
    : undefined;

  function resetDialog() {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setTouched({});
    setApiError(null);
    setSavedMessage(false);
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  async function handleLogoutAll() {
    await logoutAll();
    setPasswordOpen(false);
    navigate("/login", { replace: true });
  }

  async function handleChangePassword(event: FormEvent) {
    event.preventDefault();
    setTouched({ current: true, next: true, confirm: true });
    setApiError(null);
    setSavedMessage(false);

    if (!currentPassword || !newPassword || newPassword.length < 8 || !confirmPassword || newPassword !== confirmPassword) {
      return;
    }

    setSubmitting(true);
    try {
      const updated = await api.auth.changePassword(currentPassword, newPassword);
      applyAuthUser(updated);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setTouched({});
      setSavedMessage(true);
    } catch (err) {
      setApiError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div aria-label={t("auth.userMenuLabel")} className="flex items-center gap-3">
      <div className="flex flex-col items-end leading-tight">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium">{user.name}</span>
          {user.isSuperAdmin && (
            <Badge className="gap-1 bg-primary text-primary-foreground">
              <ShieldCheck aria-hidden className="size-3" />
              {t("auth.superAdminBadge")}
            </Badge>
          )}
        </div>
        {customGroups.length > 0 && (
          <div className="mt-0.5 flex flex-wrap justify-end gap-1">
            {customGroups.map((group) => (
              <Badge key={group.id} className="bg-muted text-[11px] font-normal text-muted-foreground">
                {group.name}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        title={t("auth.changePassword")}
        onClick={() => {
          resetDialog();
          setPasswordOpen(true);
        }}
      >
        <KeyRound aria-hidden className="size-4" />
        <span className="sr-only">{t("auth.changePassword")}</span>
      </Button>

      <Button type="button" variant="outline" size="sm" onClick={() => void handleLogout()}>
        <LogOut aria-hidden className="size-4" />
        {t("auth.signOut")}
      </Button>

      <AlertDialog
        open={passwordOpen}
        onOpenChange={(open) => {
          setPasswordOpen(open);
          if (!open) resetDialog();
        }}
      >
        <AlertDialogContent>
          <div className="space-y-1">
            <AlertDialogTitle>{t("auth.changePasswordTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {user.name} ({user.username})
            </AlertDialogDescription>
          </div>

          {apiError !== null && <ErrorAlert error={apiError} />}
          {savedMessage && (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700">
              {t("auth.passwordChanged")}
            </div>
          )}

          <form onSubmit={handleChangePassword} noValidate className="space-y-3">
            <FormField htmlFor={currentId} label={t("auth.currentPassword")} error={currentError}>
              <PasswordInput
                id={currentId}
                autoComplete="current-password"
                required
                value={currentPassword}
                aria-invalid={Boolean(currentError)}
                className={currentError ? "border-destructive" : undefined}
                onChange={(e) => setCurrentPassword(e.target.value)}
                onBlur={() => setTouched((prev) => ({ ...prev, current: true }))}
                disabled={submitting}
              />
            </FormField>
            <FormField htmlFor={newId} label={t("auth.newPassword")} error={newError}>
              <PasswordInput
                id={newId}
                autoComplete="new-password"
                required
                minLength={8}
                value={newPassword}
                aria-invalid={Boolean(newError)}
                className={newError ? "border-destructive" : undefined}
                onChange={(e) => setNewPassword(e.target.value)}
                onBlur={() => setTouched((prev) => ({ ...prev, next: true }))}
                disabled={submitting}
              />
            </FormField>
            <FormField htmlFor={confirmId} label={t("auth.confirmPassword")} error={confirmError}>
              <PasswordInput
                id={confirmId}
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                aria-invalid={Boolean(confirmError)}
                className={confirmError ? "border-destructive" : undefined}
                onChange={(e) => setConfirmPassword(e.target.value)}
                onBlur={() => setTouched((prev) => ({ ...prev, confirm: true }))}
                disabled={submitting}
              />
            </FormField>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
              <Button type="button" variant="outline" size="sm" onClick={() => void handleLogoutAll()} disabled={submitting}>
                {t("auth.signOutAll")}
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={() => setPasswordOpen(false)} disabled={submitting}>
                  {t("action.close")}
                </Button>
                <Button type="submit" disabled={submitting}>
                  {t("action.save")}
                </Button>
              </div>
            </div>
          </form>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
