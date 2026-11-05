import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DOCUMENT_TYPES } from "@/test/fixtures";
import { apiError, json, mockApi } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const body = (init: RequestInit) => JSON.parse(init.body as string) as Record<string, unknown>;
const suggestion = {
  id: 3,
  name: "Авансовый отчёт",
  reason: "Документ описывает расходы командировки.",
  status: "pending",
  occurrences: 2,
  document_id: 5,
  legal_act_id: null,
  accepted_code: null,
};

function routes(extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/document-types": ({ url }) =>
      json(
        url.searchParams.get("include_inactive") === "true"
          ? [...DOCUMENT_TYPES, { code: "old_type", name: "Старый тип", description: "Описание", is_active: false }]
          : DOCUMENT_TYPES,
      ),
    "GET /api/document-type-suggestions": () => json([suggestion]),
    ...extra,
  });
}

describe("document types", () => {
  it("accepts a suggestion only with a valid code", async () => {
    const api = routes({ "POST /api/document-type-suggestions/3/accept": () => json(DOCUMENT_TYPES[0], 201) });
    renderApp("/document-types");
    const item = (await screen.findByText("Авансовый отчёт")).closest("article")!;
    const accept = within(item).getByRole("button", { name: "Добавить тип" });
    expect(accept).toBeDisabled();
    await userEvent.type(within(item).getByLabelText(/^Код/), "Expense");
    expect(within(item).getByText(/Код должен начинаться/)).toBeInTheDocument();
    await userEvent.clear(within(item).getByLabelText(/^Код/));
    await userEvent.type(within(item).getByLabelText(/^Код/), "expense_report");
    await userEvent.click(accept);
    await waitFor(() => expect(api.calls.some((call) => call.path.endsWith("/accept"))).toBe(true));
    expect(body(api.calls.find((call) => call.path.endsWith("/accept"))!.init)).toEqual({
      code: "expense_report",
      name: "Авансовый отчёт",
      description: "Документ описывает расходы командировки.",
    });
  });

  it("dismisses a suggestion", async () => {
    const api = routes({ "POST /api/document-type-suggestions/3/dismiss": () => new Response(null, { status: 204 }) });
    renderApp("/document-types");
    const item = (await screen.findByText("Авансовый отчёт")).closest("article")!;
    await userEvent.click(within(item).getByRole("button", { name: "Отклонить" }));
    await waitFor(() => expect(api.calls.some((call) => call.path.endsWith("/dismiss"))).toBe(true));
  });

  it("explains why a type in use cannot be deactivated", async () => {
    routes({
      "DELETE /api/document-types/payroll_order": () =>
        apiError(409, "document_type_in_use", "Document type is used by: documents"),
    });
    renderApp("/document-types");
    const row = (await screen.findByText("Приказ о выплатах")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Отключить" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Отключить" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Тип документа используется");
    expect(alert).toHaveTextContent("Document type is used by: documents");
  });

  it("brings back a deactivated type", async () => {
    const api = routes({ "POST /api/document-types": () => json({ code: "old_type", name: "Старый тип", description: "Описание", is_active: true }, 201) });
    renderApp("/document-types");
    const row = (await screen.findByText("Старый тип")).closest("tr")!;
    expect(within(row).getByText("Отключён")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Включить снова" }));
    await waitFor(() => expect(api.calls.some((call) => call.method === "POST")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "POST")!.init)).toEqual({
      code: "old_type",
      name: "Старый тип",
      description: "Описание",
    });
  });

  it("edits the name and description of a type", async () => {
    const api = routes({ "PATCH /api/document-types/payroll_order": () => json(DOCUMENT_TYPES[1]) });
    renderApp("/document-types");
    const row = (await screen.findByText("Приказ о выплатах")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Изменить" }));
    await userEvent.type(within(row).getByLabelText(/^Описание/), "Приказ о премиях и доплатах.");
    await userEvent.click(within(row).getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "PATCH")!.init)).toEqual({
      name: "Приказ о выплатах",
      description: "Приказ о премиях и доплатах.",
    });
  });
});
