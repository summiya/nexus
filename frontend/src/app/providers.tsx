import { QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';

import { createQueryClient } from '../lib/query-client';
import { AppErrorBoundary } from './error-boundary';

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  return (
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </AppErrorBoundary>
  );
}
