import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createI18n } from "@/i18n";
import { ru } from "@/i18n/ru";
import { DOCUMENT_TYPES, documentItem } from "@/test/fixtures";
import { apiError, json, mockApi, page } from "@/test/fetchMock";
import { renderApp } from "@/test/render";

import { MAX_UPLOAD_BYTES, validateUpload } from "./UploadDocument";

afterEach(() => vi.unstubAllGlobals());

const i18n = createI18n("ru-RU", ru);
const file = (name: string, size = 10) => new File(["x".repeat(size)], name);

describe("validateUpload", () => {
  it("accepts the supported formats", () => {
    expect(validateUpload(file("a.TXT"), i18n)).toBeUndefined();
    expect(validateUpload(file("a.docx"), i18n)).toBeUndefined();
    expect(validateUpload(file("a.pdf"), i18n)).toBeUndefined();
  });

  it("rejects other formats, empty and too large files before sending", () => {
    expect(validateUpload(file("a.doc"), i18n)).toMatch(/не поддерживается/);
    expect(validateUpload(file("a.txt", 0), i18n)).toMatch(/пустой/);
    const large = file("a.txt");
    Object.defineProperty(large, "size", { value: MAX_UPLOAD_BYTES + 1 });
    expect(validateUpload(large, i18n)).toMatch(/больше 20 МБ/);
  });
});

describe("documents page", () => {
  it("shows the latest report counts and the confirmation need", async () => {
    mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/documents": () =>
        page([
          documentItem({
            id: 1,
            latest_report: {
              id: 5,
              total_findings: 2,
              critical_count: 0,
              high_count: 1,
              medium_count: 1,
              low_count: 0,
              created_at: "2026-11-05T10:00:00",
            },
          }),
          documentItem({
            id: 2,
            title: "unknown",
            status: "uploaded",
            classification_status: "needs_review",
            needs_configuration: true,
            confirmed_document_types: [],
          }),
        ]),
    });
    renderApp("/");
    const audited = (await screen.findByRole("link", { name: "remote_work_agreement" })).closest("tr")!;
    expect(within(audited).getByText("Соглашение о дистанционной работе")).toBeInTheDocument();
    expect(within(audited).getByText("Высокое")).toBeInTheDocument();
    const pending = screen.getByRole("link", { name: "unknown" }).closest("tr")!;
    expect(within(pending).getByText("Нужно подтвердить тип")).toBeInTheDocument();
    expect(within(pending).getByText("Аудита не было")).toBeInTheDocument();
  });

  it("uploads a file and asks to confirm an uncertain type", async () => {
    const api = mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/documents": () => page([]),
      "POST /api/documents/upload": () =>
        json(documentItem({ id: 7, title: "Договор", classification_status: "needs_review", needs_configuration: true }), 201),
    });
    renderApp("/");
    await screen.findByText("Документов пока нет. Загрузите первый.");
    await userEvent.upload(screen.getByTestId("upload-input"), file("contract.docx"));
    await userEvent.type(screen.getByLabelText("Название (необязательно)"), "Договор");
    await userEvent.click(screen.getByRole("button", { name: "Загрузить" }));

    expect(await screen.findByText("Документ «Договор» загружен.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Подтвердить тип" })).toHaveAttribute("href", "/documents/7/configure");
    const upload = api.calls.find((call) => call.method === "POST")!;
    const form = upload.init.body as FormData;
    expect((form.get("file") as File).name).toBe("contract.docx");
    expect(form.get("title")).toBe("Договор");
  });

  it("does not send a file of an unsupported format", async () => {
    const api = mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/documents": () => page([]),
    });
    renderApp("/");
    await userEvent.upload(screen.getByTestId("upload-input"), file("scan.jpg"), { applyAccept: false });
    expect(screen.getByRole("alert")).toHaveTextContent("Формат «scan.jpg» не поддерживается");
    expect(screen.getByRole("button", { name: "Загрузить" })).toBeDisabled();
    expect(api.calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("deletes a document only after confirmation", async () => {
    let documents = [documentItem()];
    const api = mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/documents": () => page(documents),
      "DELETE /api/documents/1": () => {
        documents = [];
        return new Response(null, { status: 204 });
      },
    });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    expect(api.calls.some((call) => call.method === "DELETE")).toBe(false);
    const dialog = screen.getByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(screen.getByText("Документов пока нет. Загрузите первый.")).toBeInTheDocument());
  });

  it("shows a model error of the upload in Russian", async () => {
    mockApi({
      "GET /api/document-types": () => json(DOCUMENT_TYPES),
      "GET /api/documents": () => page([]),
      "POST /api/documents/upload": () => apiError(400, "document_parse_error", "/srv/uploads/abc.pdf: no text"),
    });
    renderApp("/");
    await userEvent.upload(screen.getByTestId("upload-input"), file("scan.pdf"));
    await userEvent.click(screen.getByRole("button", { name: "Загрузить" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось извлечь текст");
    expect(alert).not.toHaveTextContent("/srv/uploads");
  });
});
