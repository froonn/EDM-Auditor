import type { ReactNode } from "react";

import { useAuth } from "./AuthProvider";
import type { Permission } from "./permissions";

interface CanProps {
  permission: Permission;
  children: ReactNode;
  fallback?: ReactNode;
}

/** Hides an action without the permission. The server must still check it. */
export function Can({ permission, children, fallback = null }: CanProps) {
  return useAuth().can(permission) ? children : fallback;
}
