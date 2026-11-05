import type { ReactNode } from "react";

import { ForbiddenPage } from "@/pages/ForbiddenPage";

import { useAuth } from "./AuthProvider";
import type { Permission } from "./permissions";

export function RequirePermission({ permission, children }: { permission: Permission; children: ReactNode }) {
  return useAuth().can(permission) ? children : <ForbiddenPage />;
}
