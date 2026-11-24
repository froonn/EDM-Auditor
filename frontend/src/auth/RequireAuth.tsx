import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { ForceChangePasswordPage } from "@/features/auth/ForceChangePasswordPage";
import { useI18n } from "@/i18n";

import { useAuth } from "./AuthProvider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { status, session } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        {t("auth.loading")}
      </div>
    );
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }

  if (session.user?.mustChangePassword) {
    return <ForceChangePasswordPage />;
  }

  return children;
}
