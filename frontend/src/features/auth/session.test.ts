import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionTokens } from "./types";

const initialTokens: SessionTokens = {
  accessToken: "access-token-x",
  refreshToken: "refresh-token-x",
  tokenType: "bearer",
  expiresIn: 900,
};

const rotatedTokens = {
  access_token: "access-token-y",
  refresh_token: "refresh-token-y",
  token_type: "bearer",
  expires_in: 900,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function expiredAccessTokenResponse(): Response {
  return jsonResponse(
    {
      error: {
        code: "ACCESS_TOKEN_EXPIRED",
        message: "Access token has expired.",
        request_id: "req_expired",
      },
    },
    401,
  );
}

function storedValues(storage: Storage): string[] {
  return Array.from({ length: storage.length }, (_, index) => {
    const key = storage.key(index);
    return key ? (storage.getItem(key) ?? "") : "";
  });
}

describe("authentication session", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("keeps the access token in memory and the refresh token in sessionStorage", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ ok: true }));

    session.establishSession(initialTokens);
    await apiRequest("/protected");

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer access-token-x");
    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-x"]);
    expect(storedValues(window.sessionStorage)).not.toContain("access-token-x");
    expect(window.localStorage.length).toBe(0);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("initializes as unauthenticated when no refresh token exists", async () => {
    const session = await import("./session");
    const { useAuthStore } = await import("./store");

    await expect(session.initializeSession()).resolves.toBe("unauthenticated");

    expect(useAuthStore.getState().status).toBe("unauthenticated");
  });

  it("restores once under repeated Strict Mode initialization and rotates storage", async () => {
    const originalSession = await import("./session");
    originalSession.establishSession(initialTokens);
    vi.resetModules();

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) =>
        Promise.resolve(
          String(input).endsWith("/auth/refresh")
            ? jsonResponse(rotatedTokens)
            : jsonResponse({ ok: true }),
        ),
      );
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");

    const firstInitialization = session.initializeSession();
    const secondInitialization = session.initializeSession();

    expect(firstInitialization).toBe(secondInitialization);
    await expect(firstInitialization).resolves.toBe("authenticated");
    await apiRequest("/protected");
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/auth/refresh"),
      ),
    ).toHaveLength(1);
    const protectedCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/protected"),
    );
    expect(new Headers(protectedCall?.[1]?.headers).get("Authorization")).toBe(
      "Bearer access-token-y",
    );
    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-y"]);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("clears the session when startup refresh returns unauthorized", async () => {
    const originalSession = await import("./session");
    originalSession.establishSession(initialTokens);
    vi.resetModules();

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "UNAUTHORIZED",
            message: "Authentication credentials are invalid.",
          },
        },
        401,
      ),
    );
    const session = await import("./session");
    const { useAuthStore } = await import("./store");

    await expect(session.initializeSession()).resolves.toBe("unauthenticated");

    expect(window.sessionStorage.length).toBe(0);
    expect(useAuthStore.getState().status).toBe("unauthenticated");
  });

  it("treats startup refresh rate limiting as retryable", async () => {
    const originalSession = await import("./session");
    originalSession.establishSession(initialTokens);
    vi.resetModules();

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "RATE_LIMITED",
            message: "Too many refresh attempts.",
          },
        },
        429,
      ),
    );
    const session = await import("./session");
    const { useAuthStore } = await import("./store");

    await expect(session.initializeSession()).resolves.toBe("unavailable");

    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-x"]);
    expect(useAuthStore.getState().status).toBe("unavailable");
  });

  it("preserves the refresh token and permits another bootstrap after a transient failure", async () => {
    const originalSession = await import("./session");
    originalSession.establishSession(initialTokens);
    vi.resetModules();

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              code: "SERVICE_UNAVAILABLE",
              message: "Authentication is temporarily unavailable.",
            },
          },
          503,
        ),
      )
      .mockResolvedValueOnce(jsonResponse(rotatedTokens));
    const session = await import("./session");
    const { useAuthStore } = await import("./store");

    await expect(session.initializeSession()).resolves.toBe("unavailable");
    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-x"]);
    expect(useAuthStore.getState().status).toBe("unavailable");

    await expect(session.initializeSession()).resolves.toBe("authenticated");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-y"]);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("allows bootstrap to retry after an authenticated request has a transient refresh failure", async () => {
    const originalSession = await import("./session");
    originalSession.establishSession(initialTokens);
    vi.resetModules();

    let refreshCall = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (!String(input).endsWith("/auth/refresh")) {
        return Promise.resolve(expiredAccessTokenResponse());
      }

      refreshCall += 1;
      if (refreshCall === 2) {
        return Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "SERVICE_UNAVAILABLE",
                message: "Authentication is temporarily unavailable.",
              },
            },
            503,
          ),
        );
      }

      return Promise.resolve(jsonResponse(rotatedTokens));
    });
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");

    await expect(session.initializeSession()).resolves.toBe("authenticated");
    await expect(apiRequest("/protected")).rejects.toMatchObject({
      status: 503,
    });
    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-y"]);
    expect(useAuthStore.getState().status).toBe("unavailable");

    await expect(session.initializeSession()).resolves.toBe("authenticated");
    expect(refreshCall).toBe(3);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("does not replace a newer login completed during startup refresh", async () => {
    const originalSession = await import("./session");
    originalSession.establishSession(initialTokens);
    vi.resetModules();

    let resolveRefresh: ((response: Response) => void) | undefined;
    const pendingRefresh = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) =>
        String(input).endsWith("/auth/refresh")
          ? pendingRefresh
          : Promise.resolve(jsonResponse({ ok: true })),
      );
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");

    const initialization = session.initializeSession();
    await vi.waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          String(input).endsWith("/auth/refresh"),
        ),
      ).toHaveLength(1);
    });
    session.establishSession({
      accessToken: "new-login-access-token",
      refreshToken: "new-login-refresh-token",
      tokenType: "bearer",
      expiresIn: 900,
    });
    resolveRefresh?.(jsonResponse(rotatedTokens));

    await expect(initialization).resolves.toBe("authenticated");
    await apiRequest("/protected");
    const protectedCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/protected"),
    );
    expect(new Headers(protectedCall?.[1]?.headers).get("Authorization")).toBe(
      "Bearer new-login-access-token",
    );
    expect(storedValues(window.sessionStorage)).toEqual([
      "new-login-refresh-token",
    ]);
  });

  it("clears the session when an expired request cannot be refreshed", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");
    session.establishSession(initialTokens);
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      Promise.resolve(
        String(input).endsWith("/auth/refresh")
          ? jsonResponse(
              {
                error: {
                  code: "UNAUTHORIZED",
                  message: "Authentication credentials are invalid.",
                },
              },
              401,
            )
          : expiredAccessTokenResponse(),
      ),
    );

    await expect(apiRequest("/protected")).rejects.toMatchObject({
      code: "UNAUTHORIZED",
    });

    expect(window.sessionStorage.length).toBe(0);
    expect(useAuthStore.getState().status).toBe("unauthenticated");
  });

  it("preserves the refresh token when refresh is temporarily unavailable", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");
    session.establishSession(initialTokens);
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      Promise.resolve(
        String(input).endsWith("/auth/refresh")
          ? jsonResponse(
              {
                error: {
                  code: "SERVICE_UNAVAILABLE",
                  message: "Authentication is temporarily unavailable.",
                },
              },
              503,
            )
          : expiredAccessTokenResponse(),
      ),
    );

    await expect(apiRequest("/protected")).rejects.toMatchObject({
      status: 503,
      code: "SERVICE_UNAVAILABLE",
    });

    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-x"]);
    expect(useAuthStore.getState().status).toBe("unavailable");
  });

  it("preserves the refresh token when an active refresh is rate limited", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");
    session.establishSession(initialTokens);
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      Promise.resolve(
        String(input).endsWith("/auth/refresh")
          ? jsonResponse(
              {
                error: {
                  code: "RATE_LIMITED",
                  message: "Too many refresh attempts.",
                },
              },
              429,
            )
          : expiredAccessTokenResponse(),
      ),
    );

    await expect(apiRequest("/protected")).rejects.toMatchObject({
      status: 429,
      code: "RATE_LIMITED",
    });

    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-x"]);
    expect(useAuthStore.getState().status).toBe("unavailable");
  });

  it("preserves the refresh token when refresh fails at the network boundary", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");
    session.establishSession(initialTokens);
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      String(input).endsWith("/auth/refresh")
        ? Promise.reject(new TypeError("Network unavailable"))
        : Promise.resolve(expiredAccessTokenResponse()),
    );

    await expect(apiRequest("/protected")).rejects.toThrow(
      "Network unavailable",
    );

    expect(storedValues(window.sessionStorage)).toEqual(["refresh-token-x"]);
    expect(useAuthStore.getState().status).toBe("unavailable");
  });

  it("uses one refresh for simultaneous expired requests and retries both with the new token", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    session.establishSession(initialTokens);

    let resolveRefresh: ((response: Response) => void) | undefined;
    const pendingRefresh = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input, init) => {
        const url = String(input);
        if (url.endsWith("/auth/refresh")) {
          return pendingRefresh;
        }

        const authorization = new Headers(init?.headers).get("Authorization");
        return Promise.resolve(
          authorization === "Bearer access-token-x"
            ? expiredAccessTokenResponse()
            : jsonResponse({ ok: true }),
        );
      });

    const firstRequest = apiRequest<{ ok: boolean }>("/protected/one");
    const secondRequest = apiRequest<{ ok: boolean }>("/protected/two");

    await vi.waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          String(input).endsWith("/auth/refresh"),
        ),
      ).toHaveLength(1);
    });
    resolveRefresh?.(jsonResponse(rotatedTokens));

    await expect(Promise.all([firstRequest, secondRequest])).resolves.toEqual([
      { ok: true },
      { ok: true },
    ]);
    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
    const retriedAuthorization = fetchMock.mock.calls
      .filter(([input]) => String(input).includes("/protected/"))
      .map(([, init]) => new Headers(init?.headers).get("Authorization"));
    expect(retriedAuthorization).toEqual([
      "Bearer access-token-x",
      "Bearer access-token-x",
      "Bearer access-token-y",
      "Bearer access-token-y",
    ]);
  });

  it("suppresses a second rotation for a late response using a stale access token", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    session.establishSession(initialTokens);

    let resolveLateResponse: ((response: Response) => void) | undefined;
    const lateResponse = new Promise<Response>((resolve) => {
      resolveLateResponse = resolve;
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input, init) => {
        const url = String(input);
        const authorization = new Headers(init?.headers).get("Authorization");
        if (url.endsWith("/auth/refresh")) {
          return Promise.resolve(jsonResponse(rotatedTokens));
        }
        if (url.endsWith("/protected/late") && authorization?.endsWith("-x")) {
          return lateResponse;
        }
        if (authorization?.endsWith("-x")) {
          return Promise.resolve(expiredAccessTokenResponse());
        }
        return Promise.resolve(jsonResponse({ ok: true }));
      });

    const lateRequest = apiRequest<{ ok: boolean }>("/protected/late");
    await expect(
      apiRequest<{ ok: boolean }>("/protected/first"),
    ).resolves.toEqual({ ok: true });
    resolveLateResponse?.(expiredAccessTokenResponse());
    await expect(lateRequest).resolves.toEqual({ ok: true });

    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/auth/refresh"),
      ),
    ).toHaveLength(1);
  });

  it("does not restore a session cleared while refresh is in progress", async () => {
    const session = await import("./session");
    const { apiRequest } = await import("../../services/api/client");
    const { useAuthStore } = await import("./store");
    session.establishSession(initialTokens);

    let resolveRefresh: ((response: Response) => void) | undefined;
    const pendingRefresh = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) =>
        String(input).endsWith("/auth/refresh")
          ? pendingRefresh
          : Promise.resolve(expiredAccessTokenResponse()),
      );

    const protectedRequest = apiRequest("/protected");
    await vi.waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          String(input).endsWith("/auth/refresh"),
        ),
      ).toHaveLength(1);
    });
    session.clearSession();
    resolveRefresh?.(jsonResponse(rotatedTokens));

    await expect(protectedRequest).rejects.toThrow(
      "The authentication session is unavailable.",
    );
    expect(window.sessionStorage.length).toBe(0);
    expect(useAuthStore.getState().status).toBe("unauthenticated");
  });

  it("fails closed when sessionStorage cannot persist the refresh token", async () => {
    const session = await import("./session");
    const { useAuthStore } = await import("./store");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage unavailable");
    });

    expect(() => session.establishSession(initialTokens)).toThrow(
      "The authentication session is unavailable.",
    );
    expect(useAuthStore.getState().status).toBe("unauthenticated");
  });
});
