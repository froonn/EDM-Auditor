import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

import type { Permission } from "./permissions";
import { LOCAL_SESSION, type Session } from "./session";

export interface Auth {
  session: Session;
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<Auth | null>(null);

interface AuthProviderProps {
  children: ReactNode;
  /** For tests. Sign-in replaces the session source here and nowhere else. */
  session?: Session;
}

export function AuthProvider({ children, session = LOCAL_SESSION }: AuthProviderProps) {
  const can = useCallback((permission: Permission) => session.permissions.has(permission), [session]);
  const value = useMemo(() => ({ session, can }), [session, can]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside AuthProvider");
  return auth;
}
