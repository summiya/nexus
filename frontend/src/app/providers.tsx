import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

import { initializeSession, useAuthStore } from "../features/auth";
import { createQueryClient } from "../lib/query-client";
import { AppErrorBoundary } from "./error-boundary";

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  const authStatus = useAuthStore((state) => state.status);

  useEffect(() => {
    void initializeSession().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") {
      queryClient.clear();
    }
  }, [authStatus, queryClient]);

  return (
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </AppErrorBoundary>
  );
}
