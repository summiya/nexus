import { create } from "zustand";

import type { AuthStatus } from "./types";

interface AuthState {
  status: AuthStatus;
}

export const useAuthStore = create<AuthState>()(() => ({
  status: "initializing",
}));

export function setAuthStatus(status: AuthStatus): void {
  useAuthStore.setState({ status });
}
