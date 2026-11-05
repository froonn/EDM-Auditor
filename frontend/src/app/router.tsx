import type { RouteObject } from "react-router";

import { RequirePermission } from "@/auth/RequirePermission";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RouteErrorPage } from "@/pages/RouteErrorPage";

import { AppLayout } from "./AppLayout";
import { APP_ROUTES } from "./routes";

export const routeObjects: RouteObject[] = [
  {
    element: <AppLayout />,
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
