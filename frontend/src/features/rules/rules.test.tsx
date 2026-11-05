import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Rule } from "@/api/types";
import { DOCUMENT_TYPES } from "@/test/fixtures";
import { apiError, json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const rule = (overrides: Partial<Rule> = {}): Rule => ({
  id: 1,
  rule_code: "ACT-1",
  name: "Срок уведомления",
  applicability_scope: "typed",
  document_types: ["remote_work_agreement"],
  applicability_confidence: 0.9,
  applicability_source: "llm",
  automatic_applicability: { scope: "typed", document_types: ["remote_work_agreement"], confidence: 0.9 },
  severity: "high",
  description: "Уведомление не позднее 10 дней.",
  check_type: "duration",
  parameters: { min_days: 10 },
  is_active: true,
  legal_act_id: 1,
  is_generated: true,
  source_quote: "Работодатель обязан уведомить\n\nне позднее 10 дней.",
  source_location: "п. 3",
  ...overrides,
});

const body = (init: RequestInit) => JSON.parse(init.body as string) as Record<string, unknown>;
const base = {
  "GET /api/document-types": () => json(DOCUMENT_TYPES),
  "GET /api/legal-acts": () => page([{ id: 1, code: "ACT-REMOTE", title: "Положение", number: null, source_url: null }]),
};

describe("rules list", () => {
  it("filters on the server and switches a rule off", async () => {
    const api = mockApi({
      ...base,
      "GET /api/rules": () => page([rule()]),
      "PATCH /api/rules/1": () => json(rule({ is_active: false })),
    });
    renderApp("/rules");
    const row = (await screen.findByRole("link", { name: "Срок уведомления" })).closest("tr")!;
    expect(within(row).getByText("Высокое")).toBeInTheDocument();
    expect(within(row).getByText("Срок")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Тип проверки"), "keyword");
    await waitFor(() =>
      expect(api.calls.some((call) => call.url.searchParams.get("check_type") === "keyword")).toBe(true),
    );
    await userEvent.click(within(row).getByRole("checkbox", { name: /Срок уведомления/ }));
    await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "PATCH")!.init)).toEqual({ is_active: false });
  });
});

describe("deactivated document types", () => {
  const withInactive = {
    ...base,
    "GET /api/document-types": () =>
      json([...DOCUMENT_TYPES, { code: "expense_report", name: "Авансовый отчёт", description: "", is_active: false }]),
  };

  it("waits only for the clicked rule and explains a refused activation", async () => {
    let answer: (response: Response) => void = () => {};
    mockApi({
      ...withInactive,
      "GET /api/rules": () =>
        page([
          rule({ id: 1, is_active: false, document_types: ["expense_report"] }),
          rule({ id: 2, name: "Сумма компенсации", rule_code: "ACT-2" }),
        ]),
      "PATCH /api/rules/1": () => new Promise<Response>((resolve) => (answer = resolve)),
    });
    renderApp("/rules");
    const first = await screen.findByRole("checkbox", { name: /Срок уведомления/ });
    const second = screen.getByRole("checkbox", { name: /Сумма компенсации/ });
    expect(screen.getByText("Авансовый отчёт (отключён)")).toBeInTheDocument();

    await userEvent.click(first);
    expect(first).toBeDisabled();
    expect(first).toBeChecked();
    expect(second).toBeEnabled();

    answer(apiError(409, "rule_document_types_inactive", "All document types of the rule are deactivated: expense_report"));
    const alert = await screen.findByRole("alert");
    expect(screen.getByText("Не удалось изменить правило «Срок уведомления»:")).toBeInTheDocument();
    await waitFor(() => expect(first).toBeEnabled());
    expect(first).not.toBeChecked();
    expect(alert).toHaveTextContent("Все типы документов этого правила отключены");
    expect(alert).toHaveTextContent("expense_report");
  });

  it("keeps every pending switch blocked until the list shows its new state", async () => {
    const states = new Map([
      [1, true],
      [2, true],
    ]);
    const answers = new Map<number, () => void>();
    mockApi({
      ...withInactive,
      "GET /api/rules": () =>
        page([
          rule({ id: 1, is_active: states.get(1) }),
          rule({ id: 2, name: "Сумма компенсации", rule_code: "ACT-2", is_active: states.get(2) }),
        ]),
      "PATCH /api/rules/1": ({ init }) =>
        new Promise<Response>((resolve) =>
          answers.set(1, () => {
            states.set(1, (JSON.parse(init.body as string) as { is_active: boolean }).is_active);
            resolve(json(rule({ id: 1 })));
          }),
        ),
      "PATCH /api/rules/2": ({ init }) =>
        new Promise<Response>((resolve) =>
          answers.set(2, () => {
            states.set(2, (JSON.parse(init.body as string) as { is_active: boolean }).is_active);
            resolve(json(rule({ id: 2 })));
          }),
        ),
    });
    renderApp("/rules");
    const first = await screen.findByRole("checkbox", { name: /Срок уведомления/ });
    const second = screen.getByRole("checkbox", { name: /Сумма компенсации/ });
    await userEvent.click(first);
    await userEvent.click(second);
    expect(first).toBeDisabled();
    expect(second).toBeDisabled();
    expect(first).not.toBeChecked();
    expect(second).not.toBeChecked();

    answers.get(1)!();
    await waitFor(() => expect(first).toBeEnabled());
    expect(first).not.toBeChecked();
    expect(second).toBeDisabled();
    expect(second).not.toBeChecked();

    answers.get(2)!();
    await waitFor(() => expect(second).toBeEnabled());
    expect(second).not.toBeChecked();
  });

  it("lists a deactivated type in the applicability form so it can be unchecked", async () => {
    const api = mockApi({
      ...withInactive,
      "GET /api/rules/1": () => json(rule({ document_types: ["expense_report", "payroll_order"] })),
      "PATCH /api/rules/1/applicability": () => json(rule({ document_types: ["payroll_order"] })),
    });
    renderApp("/rules/1");
    const panel = (await screen.findByRole("heading", { name: "Применимость" })).closest("section")!;
    const inactive = await within(panel).findByRole("checkbox", { name: "Авансовый отчёт (отключён)" });
    expect(inactive).toBeChecked();
    await userEvent.click(inactive);
    expect(within(panel).queryByRole("checkbox", { name: "Авансовый отчёт (отключён)" })).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Сохранить применимость" }));
    await waitFor(() => expect(api.calls.some((call) => call.path.endsWith("/applicability"))).toBe(true));
    expect(body(api.calls.find((call) => call.path.endsWith("/applicability"))!.init)).toEqual({
      applicability_scope: "typed",
      document_types: ["payroll_order"],
    });
  });
});

describe("rule form", () => {
  it("edits a generated rule and warns that reprocessing replaces it", async () => {
    const api = mockApi({ ...base, "GET /api/rules/1": () => json(rule()), "PATCH /api/rules/1": () => json(rule()) });
    renderApp("/rules/1");
    expect(await screen.findByText(/ваши изменения пропадут/)).toBeInTheDocument();
    expect(screen.getByText("Работодатель обязан уведомить не позднее 10 дней.")).toBeInTheDocument();
    expect(screen.getByText(/Выбор модели: По типам документов/)).toBeInTheDocument();

    const min = screen.getByLabelText("Не меньше, дней");
    await userEvent.clear(min);
    await userEvent.type(min, "14");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "PATCH")!.init)).toMatchObject({
      check_type: "duration",
      parameters: { min_days: 14 },
      severity: "high",
    });
  });

  it("creates a keyword rule with a recommendation and its applicability", async () => {
    const api = mockApi({
      ...base,
      "GET /api/rules/7": () => json(rule({ id: 7, rule_code: "MY-1", name: "Подпись", is_generated: false })),
      "POST /api/rules": () => json(rule({ id: 7 }), 201),
    });
    renderApp("/rules/new");
    await userEvent.type(await screen.findByLabelText(/^Код правила/), "MY-1");
    await userEvent.type(screen.getByLabelText("Название"), "Подпись");
    await userEvent.type(screen.getByLabelText(/Слова или фразы/), "подпись{enter}печать");
    await userEvent.selectOptions(screen.getByLabelText("Режим"), "required");
    await userEvent.type(screen.getByLabelText(/^Рекомендация/), "Добавьте подписи.");
    await userEvent.selectOptions(screen.getByLabelText(/^Область применимости/), "typed");
    const create = screen.getByRole("button", { name: "Создать" });
    expect(create).toBeDisabled();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Приказ о выплатах" }));
    await userEvent.click(create);

    await waitFor(() => expect(api.calls.some((call) => call.method === "POST")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "POST")!.init)).toEqual({
      rule_code: "MY-1",
      name: "Подпись",
      description: "",
      severity: "medium",
      check_type: "keyword",
      parameters: { keywords: ["подпись", "печать"], mode: "required", match: "literal", recommendation: "Добавьте подписи." },
      legal_act_id: null,
      applicability_scope: "typed",
      document_types: ["payroll_order"],
    });
    expect(await screen.findByRole("heading", { name: "Подпись" })).toBeInTheDocument();
  });

  it("shows which parameter the server rejected", async () => {
    mockApi({
      ...base,
      "GET /api/rules/1": () => json(rule({ check_type: "regex", parameters: { pattern: "(" } })),
      "PATCH /api/rules/1": () => apiError(422, "invalid_rule_parameters", "invalid regex: missing )"),
    });
    renderApp("/rules/1");
    await userEvent.click(await screen.findByRole("button", { name: "Сохранить" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Параметры правила заполнены неверно.");
    expect(alert).toHaveTextContent("invalid regex: missing )");
  });

  it("rejects a value that is not a number without sending it", async () => {
    const api = mockApi({ ...base, "GET /api/rules/1": () => json(rule()) });
    renderApp("/rules/1");
    const min = await screen.findByLabelText("Не меньше, дней");
    await userEvent.clear(min);
    await userEvent.type(min, "десять");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Введите число.");
    expect(api.calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("reads only the opened rule and shows a missing one as not found", async () => {
    const api = mockApi({ ...base, "GET /api/rules/1": () => json(rule()), "GET /api/rules/2": () => apiError(404, "rule_not_found") });
    renderApp("/rules/1");
    expect(await screen.findByLabelText("Не меньше, дней")).toBeInTheDocument();
    expect(api.calls.some((call) => call.path === "/api/rules")).toBe(false);

    renderApp("/rules/2");
    expect(await screen.findByText(/Страница не найдена/)).toBeInTheDocument();
  });

  it("changes the applicability separately", async () => {
    const api = mockApi({
      ...base,
      "GET /api/rules/1": () => json(rule()),
      "PATCH /api/rules/1/applicability": () => json(rule({ applicability_scope: "universal", document_types: [] })),
    });
    renderApp("/rules/1");
    const panel = (await screen.findByRole("heading", { name: "Применимость" })).closest("section")!;
    await userEvent.selectOptions(within(panel).getByLabelText(/^Область применимости/), "universal");
    await userEvent.click(within(panel).getByRole("button", { name: "Сохранить применимость" }));
    await waitFor(() => expect(api.calls.some((call) => call.path.endsWith("/applicability"))).toBe(true));
    expect(body(api.calls.find((call) => call.path.endsWith("/applicability"))!.init)).toEqual({
      applicability_scope: "universal",
      document_types: [],
    });
  });
});
