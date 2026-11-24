import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GroupItem, PermissionInfo, UserItem } from "@/api/types";
import { PERMISSIONS } from "@/auth/permissions";
import { sessionWith } from "@/auth/session";
import { DOCUMENT_TYPES, documentDetail, documentItem, report } from "@/test/fixtures";
import { json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const PERMISSION_CATALOG: PermissionInfo[] = [
  { code: "documents.upload", description: "Upload", super_admin_only: false },
  { code: "audit.run", description: "Audit", super_admin_only: false },
  { code: "reports.read", description: "Read reports", super_admin_only: false },
  { code: "groups.manage", description: "Manage groups", super_admin_only: true },
];

const CUSTOM_GROUPS: GroupItem[] = [
  {
    id: 2,
    name: "employee",
    kind: "custom",
    description: "Employees",
    owner_user_id: null,
    owner_username: null,
    member_count: 1,
    members: [{ id: 10, username: "ivan", full_name: "Ivan Petrov", is_active: true }],
    permissions: ["documents.upload", "reports.read"],
    created_at: "2026-11-24T10:00:00Z",
    updated_at: "2026-11-24T10:00:00Z",
  },
  {
    id: 3,
    name: "empty-group",
    kind: "custom",
    description: "Unused",
    owner_user_id: null,
    owner_username: null,
    member_count: 0,
    members: [],
    permissions: ["reports.read"],
    created_at: "2026-11-24T10:00:00Z",
    updated_at: "2026-11-24T10:00:00Z",
  },
];

const PERSONAL_GROUPS: GroupItem[] = [
  {
    id: 4,
    name: "ivan",
    kind: "personal",
    description: "Personal group for ivan",
    owner_user_id: 10,
    owner_username: "ivan",
    member_count: 1,
    members: [{ id: 10, username: "ivan", full_name: "Ivan Petrov", is_active: true }],
    permissions: [],
    created_at: "2026-11-24T10:00:00Z",
    updated_at: "2026-11-24T10:00:00Z",
  },
];

const USERS: UserItem[] = [
  {
    id: 1,
    username: "root",
    email: "root@example.com",
    full_name: "Root Admin",
    is_active: true,
    is_super_admin: true,
    must_change_password: false,
    personal_group_id: 1,
    custom_groups: [{ id: 5, name: "admin", kind: "custom" }],
    permissions: [...PERMISSIONS],
    created_at: "2026-11-24T10:00:00Z",
    updated_at: "2026-11-24T10:00:00Z",
    last_login_at: "2026-11-24T11:00:00Z",
  },
  {
    id: 10,
    username: "ivan",
    email: "ivan@example.com",
    full_name: "Ivan Petrov",
    is_active: true,
    is_super_admin: false,
    must_change_password: true,
    personal_group_id: 4,
    custom_groups: [{ id: 2, name: "employee", kind: "custom" }],
    permissions: ["documents.upload", "reports.read"],
    created_at: "2026-11-24T10:00:00Z",
    updated_at: "2026-11-24T10:00:00Z",
    last_login_at: null,
  },
];

describe("role-based UI screens", () => {
  it("shows waiting-for-auditor notice for employee and owner column for auditor", async () => {
    const uploadedDoc = documentItem({
      id: 7,
      title: "my_contract",
      status: "uploaded",
      owner_id: 10,
      owner_name: "Ivan Petrov",
      latest_report: null,
    });

    mockApi({
      "GET /api/documents": () => page([uploadedDoc]),
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
    });

    // Employee view: no owner column, no audit configure button, waiting notice shown.
    const employeeSession = sessionWith(
      ["documents.upload", "documents.delete_own", "reports.read", "reports.export"],
      { id: 10, name: "Ivan Petrov", username: "ivan" },
    );
    const { unmount } = renderApp("/", employeeSession);

    expect(await screen.findByText("Ожидает проверки аудитором")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Автор" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Настроить аудит" })).not.toBeInTheDocument();
    unmount();

    // Auditor view: sees owner column, waiting filter, and audit button.
    const auditorSession = sessionWith(
      ["documents.read_all", "reports.read", "audit.run", "resolutions.write"],
      { id: 20, name: "Elena Auditor", username: "elena" },
    );
    renderApp("/", auditorSession);

    expect(await screen.findByRole("columnheader", { name: "Автор" })).toBeInTheDocument();
    expect(await screen.findByText("Ivan Petrov")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Настроить аудит" })).toBeInTheDocument();
    expect(screen.getByLabelText("Статус документа")).toBeInTheDocument();
  });

  it("renders auditor read-only mode on legal acts and rules without edit actions", async () => {
    mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/legal-acts": () =>
        page([
          {
            id: 1,
            code: "TK-RB",
            title: "Трудовой кодекс",
            number: null,
            source_url: null,
            processing_status: "completed",
            chunks_total: 1,
            chunks_processed: 1,
            rules_accepted: 2,
            rules_rejected: 0,
            document_types: [],
          },
        ]),
      "GET /api/rules": () =>
        page([
          {
            id: 1,
            rule_code: "R-1",
            subject: "Отпуск",
            constraint_text: "Не менее 24 дней",
            condition: "",
            applicability_scope: "universal",
            document_types: [],
            severity: "high",
            is_active: true,
            legal_act_id: 1,
            is_generated: true,
          },
        ]),
    });

    const auditorSession = sessionWith(["reports.read", "legal_acts.read", "rules.read"], {
      id: 20,
      name: "Elena Auditor",
    });

    const { unmount } = renderApp("/legal-acts", auditorSession);
    expect(await screen.findByText("Трудовой кодекс")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Загрузка НПА" })).not.toBeInTheDocument();
    unmount();

    renderApp("/rules", auditorSession);
    expect(await screen.findByText("Отпуск")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Новое правило" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Правило «Отпуск» включено/ })).toBeDisabled();
  });

  it("lets auditors write resolutions while employees only read them", async () => {
    const user = userEvent.setup();
    const savedResolutions = [
      {
        id: 1,
        report_id: 10,
        author_id: 20,
        author_name: "Elena Auditor",
        decision: "needs_revision",
        comment: "Увеличьте отпуск",
        created_at: "2026-11-24T12:00:00Z",
      },
    ];

    const apiMock = mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/documents/1": () => json(documentDetail({ owner_name: "Ivan Petrov" })),
      "GET /api/documents/1/report": () => json(report()),
      "GET /api/reports": () => page([]),
      "GET /api/reports/10/resolutions": () => json(savedResolutions),
      "POST /api/reports/10/resolutions": (req) => {
        const body = JSON.parse(String(req.init.body)) as { decision: string; comment: string };
        const created = {
          id: 2,
          report_id: 10,
          author_id: 20,
          author_name: "Elena Auditor",
          decision: body.decision,
          comment: body.comment,
          created_at: "2026-11-24T12:05:00Z",
        };
        savedResolutions.unshift(created);
        return json(created, 201);
      },
    });

    // Employee reads resolution, no submit form.
    const { unmount } = renderApp("/documents/1/audit", sessionWith(["reports.read"]));
    expect(await screen.findByText("Увеличьте отпуск")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить резолюцию" })).not.toBeInTheDocument();
    unmount();

    // Auditor submits a new resolution.
    renderApp("/documents/1/audit", sessionWith(["reports.read", "resolutions.write"]));
    expect(await screen.findByRole("button", { name: "Сохранить резолюцию" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Комментарий"), "Исправлено верно");
    await user.click(screen.getByRole("button", { name: "Сохранить резолюцию" }));
    expect(await screen.findByText("Резолюция сохранена.")).toBeInTheDocument();
    expect(apiMock.calls.some((c) => c.method === "POST" && c.path === "/api/reports/10/resolutions")).toBe(true);
  });

  it("separates custom and personal groups, blocks non-empty deletion, and updates personal group", async () => {
    const user = userEvent.setup();
    const apiMock = mockApi({
      "GET /api/permissions": () => json(PERMISSION_CATALOG),
      "GET /api/groups": (req) => {
        const kind = req.url.searchParams.get("kind");
        if (kind === "personal") return json(PERSONAL_GROUPS);
        return json(CUSTOM_GROUPS);
      },
      "DELETE /api/groups/3": () => new Response(null, { status: 204 }),
      "PUT /api/groups/4/permissions": () => json({ ...PERSONAL_GROUPS[0], permissions: ["audit.run"] }),
    });

    const superSession = sessionWith(PERMISSIONS, {
      id: 1,
      name: "Root Admin",
      username: "root",
      isSuperAdmin: true,
    });
    renderApp("/groups", superSession);

    expect(await screen.findByRole("heading", { name: "employee" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "empty-group" })).toBeInTheDocument();

    // Non-empty group delete button is disabled; empty group delete button is enabled.
    const employeeCard = screen.getByRole("heading", { name: "employee" }).closest("section")!;
    expect(within(employeeCard).getByRole("button", { name: "Удалить" })).toBeDisabled();

    const emptyCard = screen.getByRole("heading", { name: "empty-group" }).closest("section")!;
    await user.click(within(emptyCard).getByRole("button", { name: "Удалить" }));
    await user.click(await screen.findByRole("button", { name: "Удалить", hidden: false }));
    expect(apiMock.calls.some((c) => c.method === "DELETE" && c.path === "/api/groups/3")).toBe(true);

    // Switch to Personal Groups tab and grant audit.run to Ivan's personal group.
    await user.click(screen.getByRole("tab", { name: "Личные группы пользователей" }));
    const ivanCard = (await screen.findByRole("heading", { name: "ivan" })).closest("section")!;
    await user.click(within(ivanCard).getByLabelText(/Запуск аудита/));
    await user.click(within(ivanCard).getByRole("button", { name: "Сохранить права" }));
    expect(apiMock.calls.some((c) => c.method === "PUT" && c.path === "/api/groups/4/permissions")).toBe(true);
  });

  it("manages users, revokes sessions, and displays the security audit log tab", async () => {
    const user = userEvent.setup();
    const apiMock = mockApi({
      "GET /api/users": () => page(USERS),
      "GET /api/groups": () => json(CUSTOM_GROUPS),
      "POST /api/users/10/revoke-sessions": () => json({ revoked_count: 2 }),
      "GET /api/auth/audit-log": () =>
        page([
          {
            id: 1,
            actor_user_id: 1,
            actor_username: "root",
            action: "user_sessions_revoked",
            target_type: "user",
            target_id: "10",
            details: { revoked_count: 2 },
            ip_address: "127.0.0.1",
            created_at: "2026-11-24T12:10:00Z",
          },
        ]),
    });

    const superSession = sessionWith(PERMISSIONS, {
      id: 1,
      name: "Root Admin",
      username: "root",
      isSuperAdmin: true,
    });
    renderApp("/users", superSession);

    expect(await screen.findByText("Ivan Petrov")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Передать super-admin" })).toBeInTheDocument();

    const ivanRow = screen.getByText("Ivan Petrov").closest("tr")!;
    await user.click(within(ivanRow).getByRole("button", { name: "Завершить сессии" }));
    expect(await screen.findByText("Завершено активных сессий: 2.")).toBeInTheDocument();
    expect(apiMock.calls.some((c) => c.method === "POST" && c.path === "/api/users/10/revoke-sessions")).toBe(true);

    // Switch to Security Audit Log tab.
    await user.click(screen.getByRole("tab", { name: "Журнал безопасности" }));
    expect(await screen.findByRole("cell", { name: "user_sessions_revoked" })).toBeInTheDocument();
  });
});
