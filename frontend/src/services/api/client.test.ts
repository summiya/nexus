import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, configureApiAuthentication } from "./client";

function errorResponse(code: string, message: string): Response {
  return new Response(
    JSON.stringify({ error: { code, message, request_id: "req_test" } }),
    { status: 401, headers: { "Content-Type": "application/json" } },
  );
}

describe("apiRequest", () => {
  beforeEach(() => {
    configureApiAuthentication(undefined);
  });

  it("serializes JSON requests through the configured API base URL", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await apiRequest<{ ok: boolean }>("/resource", {
      method: "POST",
      body: { name: "NEXUS" },
    });

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/resource",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "NEXUS" }),
      }),
    );
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("throws a normalized NexusApiError for failed responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: "FORBIDDEN", message: "Denied", request_id: "req_9" },
        }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(apiRequest("/resource")).rejects.toMatchObject({
      status: 403,
      code: "FORBIDDEN",
      requestId: "req_9",
    });
  });

  it("supports successful responses without content", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    await expect(
      apiRequest("/resource", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });

  it("adds the current access token to authenticated requests", async () => {
    configureApiAuthentication({
      getAccessToken: () => "access-token",
      refreshAccessToken: vi.fn(),
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest("/protected");

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer access-token");
  });

  it("does not add authorization to public requests", async () => {
    configureApiAuthentication({
      getAccessToken: () => "access-token",
      refreshAccessToken: vi.fn(),
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest("/public", {
      authentication: "none",
      headers: { Authorization: "Bearer caller-token" },
    });

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });

  it("refreshes an expired access token and retries once", async () => {
    let accessToken = "expired-access-token";
    const refreshAccessToken = vi.fn(async (expiredAccessToken: string) => {
      expect(expiredAccessToken).toBe("expired-access-token");
      accessToken = "new-access-token";
    });
    configureApiAuthentication({
      getAccessToken: () => accessToken,
      refreshAccessToken,
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        errorResponse("ACCESS_TOKEN_EXPIRED", "Access token has expired."),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await expect(apiRequest("/protected")).resolves.toEqual({ ok: true });

    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const initialHeaders = fetchMock.mock.calls[0][1]?.headers as Headers;
    const retryHeaders = fetchMock.mock.calls[1][1]?.headers as Headers;
    expect(initialHeaders.get("Authorization")).toBe(
      "Bearer expired-access-token",
    );
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-access-token");
  });

  it("does not refresh a generic unauthorized response", async () => {
    const refreshAccessToken = vi.fn();
    configureApiAuthentication({
      getAccessToken: () => "access-token",
      refreshAccessToken,
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        errorResponse("UNAUTHORIZED", "Authentication is required."),
      );

    await expect(apiRequest("/protected")).rejects.toMatchObject({
      code: "UNAUTHORIZED",
    });
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not refresh more than once when the retry also expires", async () => {
    let accessToken = "expired-access-token";
    const refreshAccessToken = vi.fn(async () => {
      accessToken = "new-access-token";
    });
    configureApiAuthentication({
      getAccessToken: () => accessToken,
      refreshAccessToken,
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        Promise.resolve(
          errorResponse("ACCESS_TOKEN_EXPIRED", "Access token has expired."),
        ),
      );

    await expect(apiRequest("/protected")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_EXPIRED",
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
