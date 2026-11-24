import { KeyRound, LogOut } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { api } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthProvider";
import { ErrorAlert } from "@/components/ErrorAlert";
import { PasswordInput } from "@/components/PasswordInput";
import { Button } from "@/components/ui/button";
import { FormField, Panel } from "@/components/ui/form";
import { useI18n } from "@/i18n";

export function ForceChangePasswordPage() {
  const { t } = useI18n();
  const { session, applyAuthUser, logout } = useAuth();
  const currentId = useId();
  const newId = useId();
  const confirmId = useId();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [touched, setTouched] = useState<{ current?: boolean; next?: boolean; confirm?: boolean }>({});
  const [apiError, setApiError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setTouched({ current: true, next: true, confirm: true });
    setApiError(null);

    if (!currentPassword || !newPassword || newPassword.length < 8 || !confirmPassword || newPassword !== confirmPassword) {
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

          {apiError !== null && <ErrorAlert error={apiError} />}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
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

            <div className="flex items-center justify-between gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => void logout()} disabled={submitting}>
                <LogOut aria-hidden className="size-4" />
                {t("auth.signOut")}
              </Button>
              <Button type="submit" disabled={submitting}>
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
