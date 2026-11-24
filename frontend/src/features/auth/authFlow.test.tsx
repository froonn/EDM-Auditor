import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "@/api/types";
import { DOCUMENT_TYPES, documentItem } from "@/test/fixtures";
import { apiError, json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

function makeAuthUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 1,
    username: "root",
    email: "root@example.com",
    full_name: "Root Admin",
    is_active: true,
    is_super_admin: true,
    must_change_password: false,
    groups: [
      { id: 1, name: "super-admin", kind: "system" },
      { id: 2, name: "admin", kind: "custom" },
      { id: 3, name: "root", kind: "personal" },
    ],
    permissions: ["reports.read", "documents.upload", "audit.run", "users.manage", "groups.manage"],
    created_at: "2026-11-24T10:00:00Z",
    last_login_at: "2026-11-24T12:00:00Z",
    ...overrides,
  };
}

describe("live authentication flow", () => {
  it("redirects unauthenticated users to /login and signs in to the requested page", async () => {
    const user = userEvent.setup();
    let authed = false;

    mockApi({
      "GET /api/auth/me": () => (authed ? json(makeAuthUser()) : apiError(401, "unauthorized")),
      "POST /api/auth/login": () => {
        authed = true;
        return json(makeAuthUser());
      },
      "GET /api/documents": () => page([documentItem()]),
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "POST /api/auth/logout": () => {
        authed = false;
        return new Response(null, { status: 204 });
      },
    });

    renderApp("/", null);

    expect(await screen.findByRole("heading", { name: "Вход в систему" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Логин или email"), "root");
    await user.type(screen.getByLabelText("Пароль"), "super-secret-password");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("link", { name: "remote_work_agreement" })).toBeInTheDocument();
    expect(screen.getByText("Root Admin")).toBeInTheDocument();
    expect(screen.getByText("super-admin")).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();

    // Sign out returns to /login.
    await user.click(screen.getByRole("button", { name: "Выйти" }));
    expect(await screen.findByRole("heading", { name: "Вход в систему" })).toBeInTheDocument();
  });

  it("shows a localized error when login fails with invalid_credentials", async () => {
    const user = userEvent.setup();
    const apiMock = mockApi({
      "GET /api/auth/me": () => apiError(401, "unauthorized"),
      "POST /api/auth/login": () => apiError(401, "invalid_credentials"),
    });

    renderApp("/login", null);

    // Submitting empty fields shows required errors without calling the API.
    await user.click(screen.getByRole("button", { name: "Войти" }));
    expect(screen.getAllByText("Поле обязательно для заполнения.")).toHaveLength(2);
    expect(apiMock.calls.some((c) => c.path === "/api/auth/login")).toBe(false);

    await user.type(screen.getByLabelText(/^Логин или email/), "root");
    await user.type(screen.getByLabelText("Пароль"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Неверный логин или пароль.")).toBeInTheDocument();
  });

  it("holds users with must_change_password on the forced change screen until updated", async () => {
    const user = userEvent.setup();
    let forced = true;

    mockApi({
      "GET /api/auth/me": () => json(makeAuthUser({ must_change_password: forced })),
      "POST /api/auth/change-password": () => {
        forced = false;
        return json(makeAuthUser({ must_change_password: false }));
      },
      "GET /api/documents": () => page([documentItem()]),
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
    });

    renderApp("/", null);

    expect(await screen.findByRole("heading", { name: "Требуется смена временного пароля" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Текущий пароль"), "temp-pass-1");
    await user.type(screen.getByLabelText("Новый пароль"), "new-strong-pass-1");
    await user.type(screen.getByLabelText("Повторите новый пароль"), "new-strong-pass-1");
    await user.click(screen.getByRole("button", { name: "Сменить пароль" }));

    expect(await screen.findByRole("link", { name: "remote_work_agreement" })).toBeInTheDocument();
  });

  it("clears the session and redirects to /login when an API call returns 401", async () => {
    let expired = false;
    mockApi({
      "GET /api/auth/me": () => (expired ? apiError(401, "unauthorized") : json(makeAuthUser())),
      "GET /api/documents": () => {
        expired = true;
        return apiError(401, "unauthorized");
      },
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
    });

    renderApp("/", null);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Вход в систему" })).toBeInTheDocument();
    });
  });
});
