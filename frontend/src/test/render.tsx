import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { Providers } from "@/app/Providers";
import { createQueryClient } from "@/app/queryClient";
import { routeObjects } from "@/app/router";
import type { AuthStatus } from "@/auth/AuthProvider";
import { LOCAL_SESSION, type Session } from "@/auth/session";

/**
 * Render the app in tests.
 * - Omit `session` to use a full-permission static test session (fast default).
 * - Pass `null` as `session` to run live `AuthProvider` backed by `GET /api/auth/me`.
 */
export function renderApp(path: string, session: Session | null = LOCAL_SESSION, authStatus?: AuthStatus) {
  const router = createMemoryRouter(routeObjects, { initialEntries: [path] });
  return render(
    <Providers
      queryClient={createQueryClient()}
      session={session === null ? undefined : session}
      authStatus={authStatus}
    >
      <RouterProvider router={router} />
    </Providers>,
  );
}
