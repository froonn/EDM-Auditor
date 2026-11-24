import { KeyRound, LogOut, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { api } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthProvider";
import { ErrorAlert } from "@/components/ErrorAlert";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField, Input } from "@/components/ui/form";
import { useI18n } from "@/i18n";

export function UserMenu() {
  const { t } = useI18n();
  const { session, logout, logoutAll, applyAuthUser } = useAuth();
  const navigate = useNavigate();

  const [passwordOpen, setPasswordOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<unknown>(null);
  const [savedMessage, setSavedMessage] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const user = session.user;
  if (!user) return null;

  const customGroups = user.groups.filter((g) => g.kind === "custom");

  function resetDialog() {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setLocalError(null);
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
    setLocalError(null);
    setApiError(null);
    setSavedMessage(false);

    if (newPassword.length < 8) {
      setLocalError(t("auth.passwordTooShort"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError(t("auth.passwordMismatch"));
      return;
    }

    setSubmitting(true);
    try {
      const updated = await api.auth.changePassword(currentPassword, newPassword);
      applyAuthUser(updated);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
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

          {localError && (
            <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {localError}
            </div>
          )}
          {apiError !== null && <ErrorAlert error={apiError} />}
          {savedMessage && (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700">
              {t("auth.passwordChanged")}
            </div>
          )}

          <form onSubmit={handleChangePassword} className="space-y-3">
            <FormField label={t("auth.currentPassword")}>
              <Input
                type="password"
                autoComplete="current-password"
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                disabled={submitting}
              />
            </FormField>
            <FormField label={t("auth.newPassword")}>
              <Input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={submitting}
              />
            </FormField>
            <FormField label={t("auth.confirmPassword")}>
              <Input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
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
                <Button type="submit" disabled={submitting || !currentPassword || !newPassword || !confirmPassword}>
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
