import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AuthProvider, type AuthStatus } from "@/auth/AuthProvider";
import type { Session } from "@/auth/session";
import { I18nProvider } from "@/i18n";

interface ProvidersProps {
  queryClient: QueryClient;
  session?: Session;
  authStatus?: AuthStatus;
  children: ReactNode;
}

export function Providers({ queryClient, session, authStatus, children }: ProvidersProps) {
  return (
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider session={session} status={authStatus}>
          {children}
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
