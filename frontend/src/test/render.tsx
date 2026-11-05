import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { Providers } from "@/app/Providers";
import { createQueryClient } from "@/app/queryClient";
import { routeObjects } from "@/app/router";
import type { Session } from "@/auth/session";

export function renderApp(path: string, session?: Session) {
  const router = createMemoryRouter(routeObjects, { initialEntries: [path] });
  return render(
    <Providers queryClient={createQueryClient()} session={session}>
      <RouterProvider router={router} />
    </Providers>,
  );
}
