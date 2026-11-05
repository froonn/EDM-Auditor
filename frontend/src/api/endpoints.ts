import { apiRequest } from "./client";

/** API calls grouped by resource. Each screen branch adds its own calls here. */
export const api = {
  health: (signal?: AbortSignal) => apiRequest<{ status: string }>("/health", { signal }),
};
