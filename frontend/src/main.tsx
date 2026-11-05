import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { Providers } from "@/app/Providers";
import { createQueryClient } from "@/app/queryClient";
import { routeObjects } from "@/app/router";

import "@/styles/index.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <Providers queryClient={createQueryClient()}>
      <RouterProvider router={createBrowserRouter(routeObjects)} />
    </Providers>
  </StrictMode>,
);
