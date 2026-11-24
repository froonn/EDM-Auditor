import type { RouteObject } from "react-router";

import { RequireAuth } from "@/auth/RequireAuth";
import { RequirePermission } from "@/auth/RequirePermission";
import { LoginPage } from "@/features/auth/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RouteErrorPage } from "@/pages/RouteErrorPage";

import { AppLayout } from "./AppLayout";
import { APP_ROUTES } from "./routes";

export const routeObjects: RouteObject[] = [
  {
    path: "/login",
    element: <LoginPage />,
    errorElement: <RouteErrorPage />,
  },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    errorElement: <RouteErrorPage />,
    children: [
      ...APP_ROUTES.map(({ path, permission, Component }) => ({
        path,
        element: (
          <RequirePermission permission={permission}>
            <Component />
          </RequirePermission>
        ),
      })),
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
