import { vi } from "vitest";

type Handler = (request: { url: URL; init: RequestInit }) => Response | Promise<Response>;

/**
 * Routes `fetch` calls by "METHOD /path" to handlers. A call without a handler fails the test, so
 * a screen cannot send an unexpected request, such as an audit that calls the model.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; url: URL; init: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname}`;
    calls.push({ method, path: url.pathname, url, init });
    const handler = routes[key];
    if (!handler) throw new Error(`Unexpected request: ${key}`);
    return handler({ url, init });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function page(items: unknown[], total = items.length) {
  return json(items, 200, { "X-Total-Count": String(total) });
}

export function apiError(status: number, code: string, message = code) {
  return json({ error: { code, message } }, status);
}
