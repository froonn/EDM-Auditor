/**
 * The only module that calls `fetch`. Everything that has to accompany each request later, such as
 * credentials for authorization, is added here, and the screens do not change.
 */

/** Codes produced by the client itself; the other codes come from the API. */
export const CLIENT_ERROR_CODES = {
  network: "network_error",
  unexpected: "unexpected_response",
  unauthorized: "unauthorized",
  forbidden: "forbidden",
} as const;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** The server's technical message, shown only as details. */
  readonly serverMessage: string | undefined;

  constructor(status: number, code: string, serverMessage?: string, options?: ErrorOptions) {
    super(serverMessage ? `${code}: ${serverMessage}` : code, options);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.serverMessage = serverMessage;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  query?: Record<string, QueryValue | QueryValue[]>;
  /** Sent as JSON. */
  json?: unknown;
  /** Sent as multipart/form-data; the browser sets the boundary. */
  form?: FormData;
  signal?: AbortSignal;
  /** The `Accept` header; JSON unless a file is downloaded. */
  accept?: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [name, raw] of Object.entries(query ?? {})) {
    const values = Array.isArray(raw) ? raw : [raw];
    for (const value of values) {
      if (value !== undefined && value !== null) params.append(name, String(value));
    }
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers = new Headers({ Accept: options.accept ?? "application/json" });
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: options.signal,
      credentials: "same-origin",
    });
  } catch (error) {
    if ((error as { name?: unknown } | null)?.name === "AbortError") throw error;
    throw new ApiError(0, CLIENT_ERROR_CODES.network, undefined, { cause: error });
  }

  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  const error = (payload as { error?: { code?: unknown; message?: unknown } } | undefined)?.error;
  if (error && typeof error.code === "string") {
    const message = typeof error.message === "string" ? error.message : undefined;
    return new ApiError(response.status, error.code, message);
  }
  // A proxy or a future authorization layer may answer without the API error format.
  if (response.status === 401) return new ApiError(401, CLIENT_ERROR_CODES.unauthorized);
  if (response.status === 403) return new ApiError(403, CLIENT_ERROR_CODES.forbidden);
  if (response.status === 502 || response.status === 504) {
    // Vite answers this way when the backend is not running.
    return new ApiError(response.status, CLIENT_ERROR_CODES.network);
  }
  return new ApiError(response.status, CLIENT_ERROR_CODES.unexpected, response.statusText);
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new ApiError(response.status, CLIENT_ERROR_CODES.unexpected, undefined, { cause: error });
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return readJson<T>(await send(path, options));
}

/** A paginated list: the total comes from the `X-Total-Count` header. */
export async function apiRequestPage<T>(path: string, options: RequestOptions = {}): Promise<Page<T>> {
  const response = await send(path, options);
  const items = await readJson<T[]>(response);
  const header = response.headers.get("X-Total-Count");
  const total = header === null ? Number.NaN : Number(header);
  if (!Array.isArray(items) || !Number.isInteger(total) || total < 0) {
    throw new ApiError(response.status, CLIENT_ERROR_CODES.unexpected, "Missing X-Total-Count");
  }
  return { items, total };
}

export interface DownloadedFile {
  blob: Blob;
  fileName: string;
}

/** A file answer: the name comes from `Content-Disposition`, errors are handled as everywhere. */
export async function apiDownload(
  path: string,
  fallbackName: string,
  options: RequestOptions = {},
): Promise<DownloadedFile> {
  const response = await send(path, { accept: "*/*", ...options });
  const fileName = fileNameFromDisposition(response.headers.get("Content-Disposition")) ?? fallbackName;
  return { blob: await response.blob(), fileName };
}

/** Prefers the UTF-8 name of RFC 5987 (`filename*`) over the plain ASCII one. */
export function fileNameFromDisposition(header: string | null): string | undefined {
  if (!header) return undefined;
  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.trim());
    } catch {
      // A malformed name falls back to the plain one.
    }
  }
  return /filename\s*=\s*"([^"]+)"/i.exec(header)?.[1] ?? /filename\s*=\s*([^;\s]+)/i.exec(header)?.[1];
}

/** Any thrown value as an ApiError, so the screens handle every failure the same way. */
export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(-1, "unknown", error instanceof Error ? error.message : undefined, {
    cause: error,
  });
}
