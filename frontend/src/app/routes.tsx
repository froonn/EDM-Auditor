import { Activity, type LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

import type { Permission } from "@/auth/permissions";
import type { MessageKey } from "@/i18n";
import { HomePage } from "@/pages/HomePage";

/**
 * Every screen is declared here once. The menu and the route protection are both built from this
 * list, so a new screen cannot be added without a permission.
 */
export interface AppRoute {
  path: string;
  titleKey: MessageKey;
  permission: Permission;
  Component: ComponentType;
  /** Shown in the main menu when set. */
  icon?: LucideIcon;
}

export const APP_ROUTES: readonly AppRoute[] = [
  { path: "/", titleKey: "nav.home", permission: "reports.read", Component: HomePage, icon: Activity },
];
