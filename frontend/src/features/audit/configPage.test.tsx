import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Rule } from "@/api/types";
import { DOCUMENT_TYPES, documentDetail, report } from "@/test/fixtures";
import { json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const rule = (id: number, name: string): Rule => ({
  id,
  rule_code: `R-${id}`,
  name,
  applicability_scope: "typed",
  document_types: ["remote_work_agreement"],
  severity: "high",
  description: "",
  check_type: "keyword",
  parameters: {},
  is_active: true,
  legal_act_id: 1,
  is_generated: true,
});

const preview = {
  document_id: 1,
  status: "ready",
  selection_mode: "manual",
  classification_status: "classified",
  classification_confidence: 1,
  confirmed_document_types: ["remote_work_agreement"],
  candidate_document_types: [],
  selected_rule_ids: [1],
  decisions: [
    { rule_id: 1, rule_code: "R-1", name: "Срок", legal_act_id: 1, applicability_scope: "typed", document_types: [], selected: true, reason: "rule_included_by_user" },
    { rule_id: 2, rule_code: "R-2", name: "Сумма", legal_act_id: 1, applicability_scope: "typed", document_types: [], selected: false, reason: "rule_excluded_by_user" },
  ],
  warnings: ["rules_with_unknown_applicability"],
  rag_recommendations: [{ legal_act_id: 1, rule_id: null, score: 0.87, threshold: 0.5, reason: "rag_candidate_above_threshold" }],
};

function routes(extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/document-types": () => json(DOCUMENT_TYPES),
    "GET /api/documents/1": () => json(documentDetail()),
    "GET /api/legal-acts": () => page([{ id: 1, code: "ACT-REMOTE", title: "Положение о дистанционной работе", number: null, source_url: null }]),
    "GET /api/rules": () => page([rule(1, "Срок"), rule(2, "Сумма")]),
    "POST /api/documents/1/audit/preview": () => json(preview),
    ...extra,
  });
}

const body = (init: RequestInit) => JSON.parse(init.body as string) as Record<string, unknown>;

describe("audit configuration", () => {
  it("previews and runs a manual selection with included and excluded rules", async () => {
    const api = routes({
      "POST /api/documents/1/audit": () => json({ report_id: 10, document_id: 1, total_findings: 3, status: "audited" }),
      "GET /api/documents/1/report": () => json(report()),
      "GET /api/reports": () => page([]),
    });
    renderApp("/documents/1/configure");
    await userEvent.click(await screen.findByRole("radio", { name: /Вручную/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Положение о дистанционной работе/ }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Выбор: Срок" }), "include");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Выбор: Сумма" }), "exclude");

    await userEvent.click(screen.getByRole("button", { name: "Показать набор правил" }));
    expect(await screen.findByText(/Будет применено правил: 1/)).toBeInTheDocument();
    expect(screen.getByText(/исключено вручную/)).toBeInTheDocument();
    expect(screen.getByText(/Есть правила с неопределённой применимостью/)).toBeInTheDocument();
    expect(screen.getByText(/сходство 87/)).toBeInTheDocument();

    const expected = {
      selection_mode: "manual",
      legal_act_ids: [1],
      included_rule_ids: [1],
      excluded_rule_ids: [2],
      confirm_all: false,
    };
    const previewCall = api.calls.find((call) => call.path.endsWith("/preview"))!;
    expect(body(previewCall.init)).toEqual(expected);

    await userEvent.click(screen.getByRole("button", { name: "Запустить аудит" }));
    expect(await screen.findByRole("region", { name: "Текст документа" })).toBeInTheDocument();
    const auditCall = api.calls.find((call) => call.path === "/api/documents/1/audit")!;
    expect(body(auditCall.init)).toEqual(expected);
  });

  it("marks the preview as stale after a change", async () => {
    routes();
    renderApp("/documents/1/configure");
    await userEvent.click(await screen.findByRole("button", { name: "Показать набор правил" }));
    await screen.findByText(/Будет применено правил/);
    await userEvent.click(screen.getByRole("radio", { name: /Вручную/ }));
    expect(screen.getByText("Настройки изменились после предпросмотра.")).toBeInTheDocument();
  });

  it("runs all rules only after an explicit confirmation", async () => {
    routes();
    renderApp("/documents/1/configure");
    await userEvent.click(await screen.findByRole("radio", { name: /Все правила/ }));
    const run = screen.getByRole("button", { name: "Запустить аудит" });
    expect(run).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Я понимаю риск/ }));
    expect(run).toBeEnabled();
  });

  it("shows the severity in its own column", async () => {
    routes();
    renderApp("/documents/1/configure");
    const row = (await screen.findByRole("combobox", { name: "Выбор: Срок" })).closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent(/^Высокое$/);
    expect(cells[1]).toHaveTextContent("Срок");
  });

  it("confirms document types manually", async () => {
    const api = routes({
      "PATCH /api/documents/1/classification": () =>
        json(documentDetail({ confirmed_document_types: ["payroll_order"], classification_source: "manual" })),
    });
    renderApp("/documents/1/configure");
    const types = await screen.findByRole("group", { name: "Подтверждённые типы" });
    await userEvent.click(await within(types).findByRole("checkbox", { name: "Соглашение о дистанционной работе" }));
    await userEvent.click(within(types).getByRole("checkbox", { name: "Приказ о выплатах" }));
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить выбранные типы" }));
    await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
    const patch = api.calls.find((call) => call.method === "PATCH")!;
    expect(body(patch.init)).toEqual({ confirmed_document_types: ["payroll_order"] });
  });
});
