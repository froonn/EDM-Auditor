import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AuthProvider } from "@/auth/AuthProvider";
import type { Session } from "@/auth/session";
import { I18nProvider } from "@/i18n";

interface ProvidersProps {
  queryClient: QueryClient;
  session?: Session;
  children: ReactNode;
}

export function Providers({ queryClient, session, children }: ProvidersProps) {
  return (
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider session={session}>{children}</AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
