import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sessionWith } from "@/auth/session";
import { renderApp } from "@/test/render";

import { APP_ROUTES } from "./routes";

afterEach(() => vi.unstubAllGlobals());

function stubHealth(response: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(response));
}

describe("application shell", () => {
  it("shows the menu and the server status", async () => {
    stubHealth(async () => Response.json({ status: "ok" }));
    renderApp("/");
    expect(screen.getByRole("navigation", { name: "Основное меню" })).toBeInTheDocument();
    expect(await screen.findByText("Сервер API отвечает.")).toBeInTheDocument();
  });

  it("explains that the backend is down and offers a retry", async () => {
    stubHealth(async () => {
      throw new TypeError("Failed to fetch");
    });
    renderApp("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Сервер API недоступен");
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });

  it("shows a not found page for an unknown address", () => {
    stubHealth(async () => Response.json({ status: "ok" }));
    renderApp("/no-such-page");
    expect(screen.getByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
  });

  it("protects routes and hides menu items without the permission", () => {
    stubHealth(async () => Response.json({ status: "ok" }));
    renderApp("/", sessionWith([]));
    expect(screen.getByRole("heading", { name: "Недостаточно прав" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Состояние системы" })).not.toBeInTheDocument();
  });

  it("declares unique paths", () => {
    const paths = APP_ROUTES.map((route) => route.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
});
