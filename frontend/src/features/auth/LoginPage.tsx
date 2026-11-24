import { LogIn } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { ErrorAlert } from "@/components/ErrorAlert";
import { PasswordInput } from "@/components/PasswordInput";
import { Button } from "@/components/ui/button";
import { FormField, Input, Panel } from "@/components/ui/form";
import { useI18n } from "@/i18n";

export function LoginPage() {
  const { t } = useI18n();
  const { status, session, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from || "/";
  const passwordId = useId();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState<{ username?: boolean; password?: boolean }>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const usernameError = touched.username && !username.trim() ? t("validation.required") : undefined;
  const passwordError = touched.password && !password ? t("validation.required") : undefined;

  if (status === "authenticated" && session.user && !session.user.mustChangePassword) {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setTouched({ username: true, password: true });
    if (!username.trim() || !password) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">{t("app.name")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("app.tagline")}</p>
        </div>

        <Panel title={t("auth.loginTitle")}>
          <p className="text-sm text-muted-foreground">{t("auth.loginSubtitle")}</p>

          {error !== null && <ErrorAlert error={error} />}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <FormField label={t("auth.username")} error={usernameError}>
              <Input
                name="username"
                autoComplete="username"
                required
                value={username}
                aria-invalid={Boolean(usernameError)}
                className={usernameError ? "border-destructive" : undefined}
                onChange={(e) => setUsername(e.target.value)}
                onBlur={() => setTouched((prev) => ({ ...prev, username: true }))}
                disabled={submitting}
              />
            </FormField>

            <FormField htmlFor={passwordId} label={t("auth.password")} error={passwordError}>
              <PasswordInput
                id={passwordId}
                name="password"
                autoComplete="current-password"
                required
                value={password}
                aria-invalid={Boolean(passwordError)}
                className={passwordError ? "border-destructive" : undefined}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => setTouched((prev) => ({ ...prev, password: true }))}
                disabled={submitting}
              />
            </FormField>

            <Button type="submit" className="w-full" disabled={submitting}>
              <LogIn aria-hidden className="size-4" />
              {submitting ? t("auth.signingIn") : t("auth.signIn")}
            </Button>
          </form>
        </Panel>
      </div>
    </div>
  );
}
