import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

import { initializeSession } from "../features/auth";
import { createQueryClient } from "../lib/query-client";
import { AppErrorBoundary } from "./error-boundary";

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  useEffect(() => {
    void initializeSession().catch(() => undefined);
  }, []);

  return (
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </AppErrorBoundary>
  );
}
