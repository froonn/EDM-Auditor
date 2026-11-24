import type { AuthUser, GroupSummary } from "@/api/types";

import { isPermission, PERMISSIONS, type Permission } from "./permissions";

export interface SessionUser {
  id: number;
  username: string;
  name: string;
  email: string;
  isSuperAdmin: boolean;
  mustChangePassword: boolean;
  groups: GroupSummary[];
}

export interface Session {
  user: SessionUser | null;
  permissions: ReadonlySet<Permission>;
}

/** Empty anonymous session before sign-in or after sign-out. */
export const ANONYMOUS_SESSION: Session = {
  user: null,
  permissions: new Set(),
};

/** Full-access session helper kept for tests that do not test authentication itself. */
export const LOCAL_SESSION: Session = {
  user: null,
  permissions: new Set(PERMISSIONS),
};

export function sessionFromAuthUser(authUser: AuthUser): Session {
  const permissions = new Set<Permission>();
  for (const raw of authUser.permissions ?? []) {
    if (isPermission(raw)) permissions.add(raw);
  }
  return {
    user: {
      id: authUser.id,
      username: authUser.username,
      name: authUser.full_name || authUser.username,
      email: authUser.email,
      isSuperAdmin: authUser.is_super_admin,
      mustChangePassword: authUser.must_change_password,
      groups: authUser.groups ?? [],
    },
    permissions,
  };
}

export function sessionWith(
  permissions: Iterable<Permission>,
  user: Partial<SessionUser> & Pick<SessionUser, "id" | "name"> | null = null,
): Session {
  const normalizedUser: SessionUser | null = user
    ? {
        id: user.id,
        username: user.username ?? user.name,
        name: user.name,
        email: user.email ?? `${user.username ?? user.name}@example.com`,
        isSuperAdmin: user.isSuperAdmin ?? false,
        mustChangePassword: user.mustChangePassword ?? false,
        groups: user.groups ?? [],
      }
    : null;
  return { user: normalizedUser, permissions: new Set(permissions) };
}
