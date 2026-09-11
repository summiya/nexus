import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

interface AppState {
  appName: string;
  isLoading: boolean;
  error: string | null;
  setIsLoading: (value: boolean) => void;
  setError: (message: string | null) => void;
  reset: () => void;
}

const AppContext = createContext<AppState | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = useMemo<AppState>(
    () => ({
      appName: 'NEXUS',
      isLoading,
      error,
      setIsLoading,
      setError,
      reset: () => {
        setIsLoading(false);
        setError(null);
      },
    }),
    [error, isLoading],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useNexusApp() {
  const context = useContext(AppContext);

  if (!context) {
    throw new Error('useNexusApp must be used within an AppProvider');
  }

  return context;
}
