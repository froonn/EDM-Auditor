import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DOCUMENT_TYPES, documentDetail, report } from "@/test/fixtures";
import { apiError, json, mockApi, page } from "@/test/fetchMock";
import { PERMISSIONS } from "@/auth/permissions";
import { sessionWith } from "@/auth/session";
import { renderApp } from "@/test/render";

const scrollIntoView = vi.fn();
beforeEach(() => {
  scrollIntoView.mockReset();
  Element.prototype.scrollIntoView = scrollIntoView;
});
afterEach(() => vi.unstubAllGlobals());

const history = [
  { id: 10, document_id: 1, document_title: "d", total_findings: 3, critical_count: 0, high_count: 1, medium_count: 1, low_count: 1, created_at: "2026-11-05T10:00:00" },
  { id: 9, document_id: 1, document_title: "d", total_findings: 1, critical_count: 0, high_count: 1, medium_count: 0, low_count: 0, created_at: "2026-11-04T10:00:00" },
];

function routes(overrides: Record<string, Parameters<typeof mockApi>[0][string]> = {}) {
  return mockApi({
    "GET /api/document-types": () => json(DOCUMENT_TYPES),
    "GET /api/documents/1": () => json(documentDetail()),
    "GET /api/documents/1/report": () => json(report()),
    "GET /api/reports": () => page(history),
    ...overrides,
  });
}

const marks = (container: HTMLElement) => [...container.querySelectorAll("mark")];

describe("audit screen", () => {
  it("highlights findings at the right place, even after an emoji", async () => {
    routes();
    renderApp("/documents/1/audit");
    const text = await screen.findByRole("region", { name: "Текст документа" });
    await waitFor(() => expect(marks(text)).toHaveLength(2));
    expect(marks(text).map((mark) => mark.textContent)).toEqual(["4 дня", "35 рублей"]);
    expect(marks(text)[0]).toHaveClass("bg-severity-high-bg");
    expect(marks(text)[1]).toHaveClass("bg-severity-medium-bg");
    expect(text).toHaveTextContent("Соглашение 😀 о дистанционной работе.");
  });

  it("shows paragraph breaks as line breaks instead of empty lines", async () => {
    routes();
    renderApp("/documents/1/audit");
    const text = await screen.findByRole("region", { name: "Текст документа" });
    await waitFor(() => expect(marks(text)).toHaveLength(2));
    expect(text.textContent).not.toContain("\n\n");
    expect(text.textContent).toContain("работе.\nУведомление");
    expect(text.textContent).toContain("4 дня.\nКомпенсация");
  });

  it("opens the card of a highlighted fragment with the model's recommendation", async () => {
    routes();
    renderApp("/documents/1/audit");
    const text = await screen.findByRole("region", { name: "Текст документа" });
    await waitFor(() => expect(marks(text)).toHaveLength(2));
    await userEvent.click(marks(text)[1]!);
    const panel = screen.getByRole("region", { name: "Список нарушений" });
    expect(within(panel).getByText("35 меньше 50.")).toBeInTheDocument();
    expect(within(panel).getByText("Повысьте компенсацию.")).toBeInTheDocument();
    // The norm is shown on one line although the act wraps it.
    expect(within(panel).getByText("Работодатель обязан уведомить не позднее 10 календарных дней.")).toBeInTheDocument();
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
  });

  it("scrolls the text to a finding chosen in the list", async () => {
    routes();
    renderApp("/documents/1/audit");
    const panel = await screen.findByRole("region", { name: "Список нарушений" });
    await userEvent.click(within(panel).getByRole("button", { name: /Срок уведомления/ }));
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(scrollIntoView.mock.contexts[0]).toHaveTextContent("4 дня");
    expect(within(panel).getByText("Уведомляйте за 10 дней.")).toBeInTheDocument();
  });

  it("keeps findings without a position in the list only", async () => {
    routes();
    renderApp("/documents/1/audit");
    const panel = await screen.findByRole("region", { name: "Список нарушений" });
    const item = within(panel).getByRole("button", { name: /Подпись сторон/ });
    expect(item).toHaveTextContent("Без привязки к тексту");
    await userEvent.click(item);
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(within(panel).getByText(/Пояснения модели нет/)).toBeInTheDocument();
  });

  it("filters findings by severity in the list and in the text", async () => {
    routes();
    renderApp("/documents/1/audit");
    const text = await screen.findByRole("region", { name: "Текст документа" });
    await waitFor(() => expect(marks(text)).toHaveLength(2));
    const filter = screen.getByRole("group", { name: "Фильтр по критичности" });
    await userEvent.click(within(filter).getByRole("button", { name: /Средняя/ }));
    expect(marks(text).map((mark) => mark.textContent)).toEqual(["4 дня"]);
    expect(screen.queryByRole("button", { name: /Размер компенсации/ })).not.toBeInTheDocument();
  });

  it("shows the summary, rejected candidates and the rule selection", async () => {
    routes();
    renderApp("/documents/1/audit");
    expect(await screen.findByText("Найдено два нарушения срока и суммы.")).toBeInTheDocument();
    expect(screen.getByText("Отклонённые моделью кандидаты (1)")).toBeInTheDocument();
    expect(screen.getByText("Это дата, а не срок")).toBeInTheDocument();
    expect(screen.getByText("Режим: Автоматически")).toBeInTheDocument();
  });

  it("lists rules without findings only when asked", async () => {
    const api = routes({
      "GET /api/rules/4": () =>
        json(
          {
            id: 4,
            rule_code: "ACT-4",
            name: "Обязательная подпись",
            description: "Документ должен содержать подписи сторон.",
            source_quote: "Соглашение подписывается\n\nобеими сторонами.",
            severity: "medium",
            check_type: "keyword",
            parameters: {},
            is_active: true,
            legal_act_id: 1,
            is_generated: true,
          },
        ),
    });
    renderApp("/documents/1/audit");
    const toggle = await screen.findByRole("button", { name: /Без нарушений 1/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("region", { name: "Правила без нарушений" })).not.toBeInTheDocument();
    await userEvent.click(toggle);
    const passed = screen.getByRole("region", { name: "Правила без нарушений" });
    expect(within(passed).getByText("Обязательная подпись")).toBeInTheDocument();
    expect(within(passed).queryByText("Срок уведомления")).not.toBeInTheDocument();
    expect(within(passed).queryByText("Командировка")).not.toBeInTheDocument();
    // Rule details are read only for the opened card.
    expect(api.calls.some((call) => call.path.startsWith("/api/rules"))).toBe(false);

    await userEvent.click(within(passed).getByRole("button", { name: /Обязательная подпись/ }));
    expect(await within(passed).findByText("Документ должен содержать подписи сторон.")).toBeInTheDocument();
    expect(api.calls.filter((call) => call.path.startsWith("/api/rules")).map((call) => call.path)).toEqual(["/api/rules/4"]);
    expect(within(passed).getByText("Документ должен содержать подписи сторон.")).toBeInTheDocument();
    expect(within(passed).getByText("Соглашение подписывается обеими сторонами.")).toBeInTheDocument();
    expect(within(passed).getByText("Средняя")).toBeInTheDocument();
  });

  it("does not load rules until a passed rule is opened, and explains a deleted rule", async () => {
    const api = routes({ "GET /api/rules/4": () => apiError(404, "rule_not_found") });
    renderApp("/documents/1/audit");
    const toggle = await screen.findByRole("button", { name: /Без нарушений 1/ });
    expect(api.calls.some((call) => call.path.startsWith("/api/rules"))).toBe(false);
    await userEvent.click(toggle);
    const passed = screen.getByRole("region", { name: "Правила без нарушений" });
    await userEvent.click(within(passed).getByRole("button", { name: /Обязательная подпись/ }));
    expect(await within(passed).findByText(/Правило удалено после аудита/)).toBeInTheDocument();
  });

  it("opens an older report from the history", async () => {
    const api = routes({
      "GET /api/documents/1/report": ({ url }) =>
        json(url.searchParams.get("report_id") === "9" ? report({ id: 9, findings: [], total_findings: 0 }) : report()),
    });
    renderApp("/documents/1/audit");
    const picker = await screen.findByRole("combobox", { name: "Отчёт" });
    await waitFor(() => expect(picker).toBeEnabled());
    await userEvent.selectOptions(picker, "9");
    expect(await screen.findByText("Это не последний отчёт документа.")).toBeInTheDocument();
    expect(screen.getByText("Нарушений не найдено.")).toBeInTheDocument();
    expect(api.calls.some((call) => call.url.searchParams.get("report_id") === "9")).toBe(true);
  });

  it("offers an audit before the first report and opens the new report", async () => {
    let audited = false;
    const api = routes({
      "GET /api/documents/1/report": ({ url }) =>
        audited && url.searchParams.get("report_id") === "10" ? json(report()) : apiError(404, "report_not_found"),
      "GET /api/reports": () => page(audited ? history.slice(0, 1) : []),
      "POST /api/documents/1/audit": () => {
        audited = true;
        return json({ report_id: 10, document_id: 1, total_findings: 3, status: "audited" });
      },
    });
    renderApp("/documents/1/audit");
    expect(await screen.findByText("Аудит этого документа ещё не проводился.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Запустить аудит" }));
    expect(await screen.findByText("Найдено два нарушения срока и суммы.")).toBeInTheDocument();
    const audit = api.calls.find((call) => call.method === "POST")!;
    expect(audit.init.body).toBe("{}");
  });

  it("asks before starting a second audit of a document in processing", async () => {
    const api = routes({ "GET /api/documents/1": () => json(documentDetail({ status: "processing" })) });
    renderApp("/documents/1/audit");
    await userEvent.click(await screen.findByRole("button", { name: "Повторить аудит" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Документ уже проверяется");
    await userEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(api.calls.some((call) => call.method === "POST")).toBe(false);
    expect(screen.getByText(/результат появится здесь сам/)).toBeInTheDocument();
  });

  it("sends the user to the configuration when the type is not confirmed", async () => {
    routes({
      "POST /api/documents/1/audit": () => apiError(409, "audit_configuration_required"),
      "GET /api/legal-acts": () => page([]),
      "GET /api/rules": () => page([]),
    });
    renderApp("/documents/1/audit");
    await userEvent.click(await screen.findByRole("button", { name: "Повторить аудит" }));
    expect(await screen.findByRole("heading", { name: "Настройка аудита" })).toBeInTheDocument();
    expect(screen.getByText(/Аудит не запущен: тип документа не подтверждён/)).toBeInTheDocument();
  });

  it("shows the audit progress below the header, not next to the buttons", async () => {
    routes({ "POST /api/documents/1/audit": () => new Promise<Response>(() => {}) });
    renderApp("/documents/1/audit");
    await userEvent.click(await screen.findByRole("button", { name: "Повторить аудит" }));
    const progress = await screen.findByText("Идёт аудит документа");
    expect(progress.closest("header")).toBeNull();
    expect(screen.getByRole("button", { name: "Повторить аудит" })).toBeDisabled();
  });

  it("explains a model failure and lets the user retry", async () => {
    let attempts = 0;
    routes({
      "POST /api/documents/1/audit": () => {
        attempts += 1;
        return apiError(429, "model_rate_limited");
      },
    });
    renderApp("/documents/1/audit");
    await userEvent.click(await screen.findByRole("button", { name: "Повторить аудит" }));
    expect(await screen.findByText(/Превышен лимит запросов/)).toBeInTheDocument();
    expect(attempts).toBe(1);
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(attempts).toBe(2));
  });

  it("downloads the HTML report with the browser's time zone and the server's file name", async () => {
    const createObjectURL = vi.fn(() => "blob:report");
    // jsdom has no object URLs; the test file runs in its own environment.
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const clicked: HTMLAnchorElement[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
    const { calls } = routes({
      "GET /api/reports/10/export": () =>
        new Response("<!DOCTYPE html><title>r</title>", {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Disposition": `attachment; filename="audit-report.html"; filename*=UTF-8''${encodeURIComponent("Отчёт аудита — договор — №10.html")}`,
          },
        }),
    });
    renderApp("/documents/1/audit");
    await userEvent.click(await screen.findByRole("button", { name: "Скачать HTML" }));

    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0]!.download).toBe("Отчёт аудита — договор — №10.html");
    expect(clicked[0]!.href).toBe("blob:report");
    const request = calls.find((call) => call.path === "/api/reports/10/export")!;
    expect(request.url.searchParams.get("format")).toBe("html");
    expect(request.url.searchParams.get("timezone")).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    click.mockRestore();
  });

  it("explains a failed export", async () => {
    routes({ "GET /api/reports/10/export": () => apiError(404, "report_not_found") });
    renderApp("/documents/1/audit");
    await userEvent.click(await screen.findByRole("button", { name: "Скачать HTML" }));
    expect(await screen.findByText("Отчёт не найден.")).toBeInTheDocument();
  });

  it("hides the export without the permission", async () => {
    routes();
    renderApp("/documents/1/audit", sessionWith(PERMISSIONS.filter((item) => item !== "reports.export")));
    await screen.findByRole("region", { name: "Текст документа" });
    expect(screen.queryByRole("button", { name: "Скачать HTML" })).not.toBeInTheDocument();
  });
});
