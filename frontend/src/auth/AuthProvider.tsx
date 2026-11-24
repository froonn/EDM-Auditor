import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";

import { ApiError, setUnauthorizedHandler } from "@/api/client";
import { api } from "@/api/endpoints";
import type { AuthUser } from "@/api/types";

import type { Permission } from "./permissions";
import { ANONYMOUS_SESSION, sessionFromAuthUser, type Session } from "./session";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export interface Auth {
  status: AuthStatus;
  session: Session;
  can: (permission: Permission) => boolean;
  canAny: (...permissions: Permission[]) => boolean;
  login: (username: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
  applyAuthUser: (user: AuthUser) => void;
  refreshSession: () => Promise<void>;
}

const AUTH_QUERY_KEY = ["auth", "me"] as const;

const AuthContext = createContext<Auth | null>(null);

interface AuthProviderProps {
  children: ReactNode;
  /**
   * For tests: pass a static Session to bypass GET /api/auth/me,
   * or omit (undefined) to run the real server-backed session flow.
   */
  session?: Session;
  /** Optional status override for tests when a static session is supplied. */
  status?: AuthStatus;
}

export function AuthProvider({ children, session: staticSession, status: staticStatus }: AuthProviderProps) {
  const queryClient = useQueryClient();
  const isLive = staticSession === undefined;

  const meQuery = useQuery<AuthUser | null, ApiError>({
    queryKey: AUTH_QUERY_KEY,
    enabled: isLive,
    retry: false,
    refetchOnWindowFocus: true,
    queryFn: async ({ signal }) => {
      try {
        return await api.auth.me(signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return null;
        }
        throw error;
      }
    },
  });

  const clearNonAuthCache = useCallback(() => {
    queryClient.removeQueries({
      predicate: (query) => query.queryKey[0] !== AUTH_QUERY_KEY[0],
    });
  }, [queryClient]);

  useEffect(() => {
    if (!isLive) return;
    setUnauthorizedHandler(() => {
      clearNonAuthCache();
      queryClient.setQueryData<AuthUser | null>(AUTH_QUERY_KEY, null);
    });
    return () => setUnauthorizedHandler(null);
  }, [isLive, queryClient, clearNonAuthCache]);

  const applyAuthUser = useCallback(
    (user: AuthUser) => {
      queryClient.setQueryData<AuthUser | null>(AUTH_QUERY_KEY, user);
    },
    [queryClient],
  );

  const login = useCallback(
    async (username: string, password: string) => {
      const user = await api.auth.login(username, password);
      clearNonAuthCache();
      queryClient.setQueryData<AuthUser | null>(AUTH_QUERY_KEY, user);
      return user;
    },
    [queryClient, clearNonAuthCache],
  );

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      clearNonAuthCache();
      queryClient.setQueryData<AuthUser | null>(AUTH_QUERY_KEY, null);
    }
  }, [queryClient, clearNonAuthCache]);

  const logoutAll = useCallback(async () => {
    try {
      await api.auth.logoutAll();
    } finally {
      clearNonAuthCache();
      queryClient.setQueryData<AuthUser | null>(AUTH_QUERY_KEY, null);
    }
  }, [queryClient, clearNonAuthCache]);

  const refreshSession = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
  }, [queryClient]);

  const session: Session = useMemo(() => {
    if (!isLive) return staticSession;
    if (!meQuery.data) return ANONYMOUS_SESSION;
    return sessionFromAuthUser(meQuery.data);
  }, [isLive, staticSession, meQuery.data]);

  const status: AuthStatus = useMemo(() => {
    if (!isLive) return staticStatus ?? "authenticated";
    if (meQuery.isPending) return "loading";
    return meQuery.data ? "authenticated" : "unauthenticated";
  }, [isLive, staticStatus, meQuery.isPending, meQuery.data]);

  const can = useCallback((permission: Permission) => session.permissions.has(permission), [session]);
  const canAny = useCallback(
    (...permissions: Permission[]) => permissions.some((p) => session.permissions.has(p)),
    [session],
  );

  const value = useMemo<Auth>(
    () => ({
      status,
      session,
      can,
      canAny,
      login,
      logout,
      logoutAll,
      applyAuthUser,
      refreshSession,
    }),
    [status, session, can, canAny, login, logout, logoutAll, applyAuthUser, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside AuthProvider");
  return auth;
}
