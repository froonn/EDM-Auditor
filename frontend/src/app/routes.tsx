import { FileText, type LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

import type { Permission } from "@/auth/permissions";
import { AuditConfigPage } from "@/features/audit/AuditConfigPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { DocumentsPage } from "@/features/documents/DocumentsPage";
import type { MessageKey } from "@/i18n";

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
  { path: "/", titleKey: "nav.documents", permission: "reports.read", Component: DocumentsPage, icon: FileText },
  { path: "/documents/:id/audit", titleKey: "audit.title", permission: "reports.read", Component: AuditPage },
  { path: "/documents/:id/configure", titleKey: "config.title", permission: "audit.run", Component: AuditConfigPage },
];
