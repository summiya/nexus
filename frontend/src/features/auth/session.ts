import { configureApiAuthentication } from "../../services/api/client";
import { NexusApiError } from "../../services/api/error";
import { refreshSession } from "./api";
import { setAuthStatus } from "./store";
import type { AuthStatus, SessionTokens } from "./types";

const REFRESH_TOKEN_STORAGE_KEY = "nexus.authentication.refresh-token";
const SESSION_UNAVAILABLE_MESSAGE =
  "The authentication session is unavailable.";

let accessToken: string | null = null;
let refreshInFlight: Promise<string> | undefined;
let initializationInFlight: Promise<AuthStatus> | undefined;
let sessionRevision = 0;

function sessionUnavailable(): Error {
  return new Error(SESSION_UNAVAILABLE_MESSAGE);
}

function readRefreshToken(): string | null {
  try {
    return window.sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
  } catch {
    throw sessionUnavailable();
  }
}

function writeRefreshToken(refreshToken: string): void {
  try {
    window.sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
  } catch {
    throw sessionUnavailable();
  }
}

function removeRefreshToken(): void {
  try {
    window.sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  } catch {
    // In-memory state is still cleared when browser storage is unavailable.
  }
}

function getAccessToken(): string | null {
  return accessToken;
}

function suspendSession(): void {
  accessToken = null;
  sessionRevision += 1;
  initializationInFlight = undefined;
  setAuthStatus("unavailable");
}

function refreshFailureInvalidatesSession(error: unknown): boolean {
  return error instanceof NexusApiError && error.status === 401;
}

function refreshFailureIsTransient(error: unknown): boolean {
  return (
    error instanceof TypeError ||
    (error instanceof NexusApiError && error.status >= 500)
  );
}

export function establishSession(tokens: SessionTokens): void {
  try {
    writeRefreshToken(tokens.refreshToken);
  } catch (error) {
    accessToken = null;
    removeRefreshToken();
    setAuthStatus("unauthenticated");
    throw error;
  }

  accessToken = tokens.accessToken;
  sessionRevision += 1;
  setAuthStatus("authenticated");
}

export function clearSession(): void {
  accessToken = null;
  sessionRevision += 1;
  initializationInFlight = undefined;
  removeRefreshToken();
  setAuthStatus("unauthenticated");
}

async function refreshStoredSession(): Promise<string> {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  let refreshToken: string | null;
  try {
    refreshToken = readRefreshToken();
  } catch (error) {
    suspendSession();
    throw error;
  }

  if (!refreshToken) {
    clearSession();
    throw sessionUnavailable();
  }

  const refreshRevision = sessionRevision;
  const refresh = refreshSession(refreshToken)
    .then((tokens) => {
      if (sessionRevision !== refreshRevision) {
        throw sessionUnavailable();
      }

      establishSession(tokens);
      return tokens.accessToken;
    })
    .catch((error: unknown) => {
      if (sessionRevision === refreshRevision) {
        if (refreshFailureInvalidatesSession(error)) {
          clearSession();
        } else {
          suspendSession();
        }
      }
      throw error;
    })
    .finally(() => {
      if (refreshInFlight === refresh) {
        refreshInFlight = undefined;
      }
    });

  refreshInFlight = refresh;
  return refresh;
}

async function refreshExpiredAccessToken(
  expiredAccessToken: string,
): Promise<void> {
  if (accessToken && accessToken !== expiredAccessToken) {
    return;
  }

  await refreshStoredSession();
}

export function initializeSession(): Promise<AuthStatus> {
  if (initializationInFlight) {
    return initializationInFlight;
  }

  setAuthStatus("initializing");
  const initialization = (async () => {
    const initializationRevision = sessionRevision;
    try {
      if (!readRefreshToken()) {
        clearSession();
        return "unauthenticated";
      }

      await refreshStoredSession();
      return "authenticated";
    } catch (error: unknown) {
      if (accessToken) {
        return "authenticated";
      }

      if (refreshFailureInvalidatesSession(error)) {
        return "unauthenticated";
      }

      if (refreshFailureIsTransient(error)) {
        return "unavailable";
      }

      try {
        if (!readRefreshToken()) {
          return "unauthenticated";
        }
      } catch {
        // Storage failures are retryable and must not destroy stored credentials.
      }

      if (sessionRevision === initializationRevision) {
        suspendSession();
      }

      throw error;
    }
  })();

  const trackedInitialization = initialization.catch((error: unknown) => {
    if (initializationInFlight === trackedInitialization) {
      initializationInFlight = undefined;
    }
    throw error;
  });

  initializationInFlight = trackedInitialization;
  return trackedInitialization;
}

configureApiAuthentication({
  getAccessToken,
  refreshAccessToken: refreshExpiredAccessToken,
});
