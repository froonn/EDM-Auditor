import { KeyRound, LogOut } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthProvider";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel } from "@/components/ui/form";
import { useI18n } from "@/i18n";

export function ForceChangePasswordPage() {
  const { t } = useI18n();
  const { session, applyAuthUser, logout } = useAuth();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLocalError(null);
    setApiError(null);

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
    } catch (err) {
      setApiError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md space-y-4">
        <Panel title={t("auth.forceChangePasswordTitle")}>
          <p className="text-sm text-muted-foreground">
            {t("auth.forceChangePasswordDescription")}
          </p>
          {session.user && (
            <p className="text-xs text-muted-foreground">
              {session.user.name} ({session.user.username})
            </p>
          )}

          {localError && (
            <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {localError}
            </div>
          )}
          {apiError !== null && <ErrorAlert error={apiError} />}

          <form onSubmit={handleSubmit} className="space-y-4">
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

            <div className="flex items-center justify-between gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => void logout()} disabled={submitting}>
                <LogOut aria-hidden className="size-4" />
                {t("auth.signOut")}
              </Button>
              <Button type="submit" disabled={submitting || !currentPassword || !newPassword || !confirmPassword}>
                <KeyRound aria-hidden className="size-4" />
                {t("auth.changePassword")}
              </Button>
            </div>
          </form>
        </Panel>
      </div>
    </div>
  );
}
