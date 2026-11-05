import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiDownload, apiRequest, apiRequestPage, asApiError, buildUrl, fileNameFromDisposition } from "./client";

function mockFetch(response: Response | Error | DOMException) {
  const fetchMock = vi.fn(async () => {
    if (!(response instanceof Response)) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("buildUrl", () => {
  it("skips empty values and repeats list parameters", () => {
    expect(buildUrl("/api/rules", { is_active: true, document_type: undefined, ids: [1, 2], q: null })).toBe(
      "/api/rules?is_active=true&ids=1&ids=2",
    );
    expect(buildUrl("/api/rules")).toBe("/api/rules");
  });
});

describe("apiRequest", () => {
  it("returns the JSON body", async () => {
    mockFetch(json({ status: "ok" }));
    await expect(apiRequest("/health")).resolves.toEqual({ status: "ok" });
  });

  it("sends JSON with POST and a content type", async () => {
    const fetchMock = mockFetch(json({ id: 1 }, { status: 201 }));
    await apiRequest("/api/rules", { json: { name: "x" } });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(init.body).toBe('{"name":"x"}');
  });

  it("leaves the multipart boundary to the browser", async () => {
    const fetchMock = mockFetch(json({ id: 1 }, { status: 201 }));
    const form = new FormData();
    form.append("title", "x");
    await apiRequest("/api/documents/upload", { form });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    expect(init.body).toBe(form);
  });

  it("returns nothing for 204", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(apiRequest("/api/rules/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("reads the API error format", async () => {
    mockFetch(json({ error: { code: "model_rate_limited", message: "Rate limited" } }, { status: 429 }));
    const error = await apiRequest("/api/documents/1/audit", { method: "POST" }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, code: "model_rate_limited", serverMessage: "Rate limited" });
  });

  it("reports an unreachable server as a network error", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    await expect(apiRequest("/health")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("treats a proxy error without a body as a network error", async () => {
    mockFetch(new Response("", { status: 502 }));
    await expect(apiRequest("/health")).rejects.toMatchObject({ code: "network_error" });
  });

  it("keeps the model timeout code when the API sends one", async () => {
    mockFetch(json({ error: { code: "model_timeout", message: "Timeout" } }, { status: 504 }));
    await expect(apiRequest("/health")).rejects.toMatchObject({ code: "model_timeout" });
  });

  it("recognizes 401 and 403 without the API error format", async () => {
    mockFetch(new Response("", { status: 401 }));
    await expect(apiRequest("/api/rules")).rejects.toMatchObject({ code: "unauthorized" });
    mockFetch(new Response("", { status: 403 }));
    await expect(apiRequest("/api/rules")).rejects.toMatchObject({ code: "forbidden" });
  });

  it("rejects a successful response that is not JSON", async () => {
    mockFetch(new Response("<html>", { status: 200 }));
    await expect(apiRequest("/health")).rejects.toMatchObject({ code: "unexpected_response" });
  });

  it("passes cancellation through", async () => {
    mockFetch(new DOMException("Aborted", "AbortError"));
    await expect(apiRequest("/health")).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("apiRequestPage", () => {
  it("reads the total from X-Total-Count", async () => {
    mockFetch(json([{ id: 1 }], { headers: { "X-Total-Count": "42" } }));
    await expect(apiRequestPage("/api/documents")).resolves.toEqual({ items: [{ id: 1 }], total: 42 });
  });

  it("fails without X-Total-Count instead of guessing the total", async () => {
    mockFetch(json([]));
    await expect(apiRequestPage("/api/documents")).rejects.toMatchObject({ code: "unexpected_response" });
  });
});

describe("asApiError", () => {
  it("wraps other errors", () => {
    expect(asApiError(new Error("boom"))).toMatchObject({ code: "unknown", serverMessage: "boom" });
    const original = new ApiError(404, "rule_not_found");
    expect(asApiError(original)).toBe(original);
  });
});

describe("file downloads", () => {
  it("prefers the UTF-8 file name and falls back to the plain one", () => {
    expect(fileNameFromDisposition(`attachment; filename="a.html"; filename*=UTF-8''%D0%BE%D1%82%D1%87%D1%91%D1%82.html`)).toBe(
      "отчёт.html",
    );
    expect(fileNameFromDisposition('attachment; filename="a.html"')).toBe("a.html");
    expect(fileNameFromDisposition("attachment; filename=b.html")).toBe("b.html");
    expect(fileNameFromDisposition(`attachment; filename="c.html"; filename*=UTF-8''%E0%A4%A`)).toBe("c.html");
    expect(fileNameFromDisposition(null)).toBeUndefined();
  });

  it("returns the body as a file and reads errors like other requests", async () => {
    const fetchMock = mockFetch(new Response("<html>", { headers: { "Content-Type": "text/html" } }));
    const file = await apiDownload("/api/reports/1/export", "fallback.html");
    expect(file.fileName).toBe("fallback.html");
    expect(await file.blob.text()).toBe("<html>");
    const headers = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Headers;
    expect(headers.get("Accept")).toBe("*/*");

    mockFetch(json({ error: { code: "report_not_found", message: "missing" } }, { status: 404 }));
    await expect(apiDownload("/api/reports/1/export", "f.html")).rejects.toMatchObject({ code: "report_not_found" });
  });
});
