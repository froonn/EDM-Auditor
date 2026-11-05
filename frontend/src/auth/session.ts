import { PERMISSIONS, type Permission } from "./permissions";

export interface SessionUser {
  id: number;
  name: string;
}

export interface Session {
  /** `null` while the system has no sign-in. */
  user: SessionUser | null;
  permissions: ReadonlySet<Permission>;
}

/** Without authorization the local user may do everything. */
export const LOCAL_SESSION: Session = {
  user: null,
  permissions: new Set(PERMISSIONS),
};

export function sessionWith(permissions: Iterable<Permission>, user: SessionUser | null = null): Session {
  return { user, permissions: new Set(permissions) };
}
