import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sessionWith } from "@/auth/session";
import { DOCUMENT_TYPES, documentItem } from "@/test/fixtures";
import { json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

import { APP_ROUTES } from "./routes";

afterEach(() => vi.unstubAllGlobals());

const listRoutes = {
  "GET /api/documents": () => page([documentItem()]),
  "GET /api/document-types": () => json(DOCUMENT_TYPES),
};

describe("application shell", () => {
  it("shows the menu and the documents", async () => {
    mockApi(listRoutes);
    renderApp("/");
    expect(screen.getByRole("navigation", { name: "Основное меню" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "remote_work_agreement" })).toBeInTheDocument();
  });

  it("explains that the backend is down and offers a retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    renderApp("/");
    expect(await screen.findByText(/Сервер API недоступен/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });

  it("shows a not found page for an unknown address", () => {
    mockApi(listRoutes);
    renderApp("/no-such-page");
    expect(screen.getByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
  });

  it("protects routes and hides menu items without the permission", () => {
    mockApi(listRoutes);
    renderApp("/", sessionWith([]));
    expect(screen.getByRole("heading", { name: "Недостаточно прав" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Документы" })).not.toBeInTheDocument();
  });

  it("declares unique paths", () => {
    const paths = APP_ROUTES.map((route) => route.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
});
