import { NavLink, Outlet } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

import { APP_ROUTES } from "./routes";

export function AppLayout() {
  const { t } = useI18n();
  const { can } = useAuth();
  const menu = APP_ROUTES.filter((route) => route.icon && can(route.permission));

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b bg-card">
        <div className="flex h-14 items-center gap-8 px-6">
          <div className="leading-tight">
            <p className="font-semibold">{t("app.name")}</p>
            <p className="text-xs text-muted-foreground">{t("app.tagline")}</p>
          </div>
          <nav aria-label={t("nav.main")} className="flex flex-1 gap-1">
            {menu.map(({ path, titleKey, icon: Icon }) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent",
                    isActive && "bg-accent font-medium text-accent-foreground",
                  )
                }
              >
                {Icon && <Icon aria-hidden className="size-4" />}
                {t(titleKey)}
              </NavLink>
            ))}
          </nav>
          {/* Reserved for the user menu after sign-in is added. */}
          <div data-slot="user-menu" />
        </div>
      </header>
      <main className="flex-1 px-6 py-6">
        <Outlet />
      </main>
      <footer className="border-t px-6 py-3 text-xs text-muted-foreground">{t("app.disclaimer")}</footer>
    </div>
  );
}
