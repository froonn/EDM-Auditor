import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // Errors are shown at once with a retry button. Requests that call the model are mutations
      // and are never repeated automatically: a repeat spends the model's request limit again.
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}
