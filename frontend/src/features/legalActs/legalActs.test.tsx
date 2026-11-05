import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DOCUMENT_TYPES } from "@/test/fixtures";
import { apiError, json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const act = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  code: "ACT-REMOTE",
  title: "Положение о дистанционной работе",
  number: null,
  source_url: null,
  processing_status: "completed",
  chunks_total: 1,
  chunks_processed: 1,
  rules_accepted: 3,
  rules_rejected: 0,
  document_types: [],
  ...overrides,
});

const body = (init: RequestInit) => JSON.parse(init.body as string) as Record<string, unknown>;

describe("legal acts", () => {
  it("uploads a TXT act with its fields and types", async () => {
    let uploaded = false;
    const api = mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/legal-acts": () => page(uploaded ? [act()] : []),
      "POST /api/legal-acts/upload": () => {
        uploaded = true;
        return json(act(), 201);
      },
    });
    renderApp("/legal-acts");
    await screen.findByText("НПА не загружены.");
    await userEvent.type(screen.getByLabelText(/^Код/), "ACT-REMOTE");
    await userEvent.type(screen.getByLabelText("Название"), "Положение о дистанционной работе");
    await userEvent.click(await screen.findByRole("checkbox", { name: "Соглашение о дистанционной работе" }));
    await userEvent.upload(screen.getByLabelText("Файл TXT"), new File(["Текст"], "act.txt"));
    await userEvent.click(screen.getByRole("button", { name: "Загрузить и извлечь правила" }));

    expect(await screen.findByText(/принято правил 3, отклонено 0/)).toBeInTheDocument();
    const form = api.calls.find((call) => call.method === "POST")!.init.body as FormData;
    expect(form.get("code")).toBe("ACT-REMOTE");
    expect(form.get("document_types")).toBe("remote_work_agreement");
    expect(form.has("number")).toBe(false);
    expect(await screen.findByRole("link", { name: "Положение о дистанционной работе" })).toBeInTheDocument();
  });

  it("accepts a dropped file in the same drop zone as documents", async () => {
    mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/legal-acts": () => page([]),
    });
    renderApp("/legal-acts");
    const zone = (await screen.findByText("Перетащите файл сюда или выберите его")).closest("div")!.parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["Текст"], "act.txt")] } });
    expect(screen.getByText("Выбран файл: act.txt")).toBeInTheDocument();
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["x"], "act.pdf")] } });
    expect(screen.getByRole("alert")).toHaveTextContent("только в формате TXT");
  });

  it("refuses formats other than TXT before sending", async () => {
    const api = mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/legal-acts": () => page([]),
    });
    renderApp("/legal-acts");
    await userEvent.upload(screen.getByLabelText("Файл TXT"), new File(["x"], "act.docx"), { applyAccept: false });
    expect(screen.getByRole("alert")).toHaveTextContent("только в формате TXT");
    expect(api.calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("explains a model error during the upload", async () => {
    mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/legal-acts": () => page([]),
      "POST /api/legal-acts/upload": () => apiError(429, "model_rate_limited"),
    });
    renderApp("/legal-acts");
    await userEvent.type(screen.getByLabelText(/^Код/), "A");
    await userEvent.type(screen.getByLabelText("Название"), "B");
    await userEvent.upload(screen.getByLabelText("Файл TXT"), new File(["x"], "act.txt"));
    await userEvent.click(screen.getByRole("button", { name: "Загрузить и извлечь правила" }));
    expect(await screen.findByText(/Превышен лимит запросов/)).toBeInTheDocument();
    expect(screen.getByText(/не загружайте повторно/)).toBeInTheDocument();
  });
});

describe("legal act page", () => {
  function routes(extra: Parameters<typeof mockApi>[0] = {}) {
    return mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/legal-acts/1": () =>
        json({ ...act({ processing_status: "needs_reprocessing" }), article_text: "Положение.\n\nПункт 1." }),
      "GET /api/legal-acts/1/diagnostics": () =>
        json({
          legal_act_id: 1,
          processing_status: "completed",
          chunks_total: 1,
          chunks_processed: 1,
          rules_accepted: 3,
          rules_rejected: 0,
          diagnostics: [
            { id: 1, chunk_id: "ACT-REMOTE-0", status: "failed", error_code: "invalid_quote", diagnostic_message: "quote not found", rules_total: 1, rules_accepted: 0, rules_rejected: 1, processing_version: "2", created_at: "2026-11-05T10:00:00" },
          ],
        }),
      "GET /api/rules": () => page([]),
      ...extra,
    });
  }

  it("shows that the rules are outdated and the diagnostics", async () => {
    routes();
    renderApp("/legal-acts/1");
    expect(await screen.findByText(/правила извлечены из старого текста/)).toBeInTheDocument();
    expect(await screen.findByText("quote not found")).toBeInTheDocument();
    expect(screen.getByText("Ошибка")).toBeInTheDocument();
  });

  it("sends only the changed fields", async () => {
    const api = routes({ "PATCH /api/legal-acts/1": () => json(act()) });
    renderApp("/legal-acts/1");
    const title = await screen.findByLabelText("Название");
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    await userEvent.clear(title);
    await userEvent.type(title, "Новое название");
    await userEvent.click(save);
    await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "PATCH")!.init)).toEqual({ title: "Новое название" });
  });

  it("edits the text one paragraph per line and stores paragraphs again", async () => {
    const api = routes({ "PATCH /api/legal-acts/1": () => json(act()) });
    renderApp("/legal-acts/1");
    const text = await screen.findByLabelText(/^Текст НПА/);
    expect(text).toHaveValue("Положение.\nПункт 1.");
    await userEvent.type(text, "{enter}Пункт 2.");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(body(api.calls.find((call) => call.method === "PATCH")!.init)).toEqual({
      article_text: "Положение.\n\nПункт 1.\n\nПункт 2.",
    });
  });

  it("reprocesses only after a warning about lost manual changes", async () => {
    const api = routes({ "POST /api/legal-acts/1/reprocess": () => json(act()) });
    renderApp("/legal-acts/1");
    await userEvent.click(await screen.findByRole("button", { name: "Обработать заново" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Ручные изменения правил этого НПА");
    expect(api.calls.some((call) => call.path.endsWith("/reprocess"))).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Обработать заново" }));
    await waitFor(() => expect(api.calls.some((call) => call.path.endsWith("/reprocess"))).toBe(true));
  });

  it("deletes the act after confirmation and returns to the list", async () => {
    routes({
      "DELETE /api/legal-acts/1": () => new Response(null, { status: 204 }),
      "GET /api/legal-acts": () => page([]),
    });
    renderApp("/legal-acts/1");
    await userEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Удалить" }));
    expect(await screen.findByRole("heading", { name: "Нормативные правовые акты" })).toBeInTheDocument();
  });
});
