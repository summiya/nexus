import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, apiResponse, configureApiAuthentication } from "./client";

function errorResponse(code: string, message: string): Response {
  return new Response(
    JSON.stringify({ error: { code, message, request_id: "req_test" } }),
    { status: 401, headers: { "Content-Type": "application/json" } },
  );
}

describe("API client", () => {
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

  it("returns an authenticated successful Response without consuming it", async () => {
    configureApiAuthentication({
      getAccessToken: () => "access-token",
      refreshAccessToken: vi.fn(),
    });
    const response = new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response);

    await expect(apiResponse("/protected")).resolves.toBe(response);

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(response.bodyUsed).toBe(false);
  });

  it("does not automatically add authorization to public requests", async () => {
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

    await apiResponse("/public", {
      authentication: "none",
    });

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });

  it("preserves explicitly supplied authorization on public requests", async () => {
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

    await apiResponse("/public", {
      authentication: "none",
      headers: { Authorization: "Bearer caller-token" },
    });

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer caller-token");
  });

  it("does not replace or refresh explicitly supplied authorization", async () => {
    const refreshAccessToken = vi.fn();
    configureApiAuthentication({
      getAccessToken: () => "access-token",
      refreshAccessToken,
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        errorResponse("ACCESS_TOKEN_EXPIRED", "Access token has expired."),
      );

    await expect(
      apiResponse("/protected", {
        headers: { Authorization: "Bearer caller-token" },
      }),
    ).rejects.toMatchObject({ code: "ACCESS_TOKEN_EXPIRED" });

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer caller-token");
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
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

    const response = await apiResponse("/protected");

    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(response.bodyUsed).toBe(false);
    await expect(response.json()).resolves.toEqual({ ok: true });
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

    await expect(apiResponse("/protected")).rejects.toMatchObject({
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

    await expect(apiResponse("/protected")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_EXPIRED",
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
