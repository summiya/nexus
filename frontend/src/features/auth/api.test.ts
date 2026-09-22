import { beforeEach, describe, expect, it, vi } from "vitest";

import { configureApiAuthentication } from "../../services/api/client";
import { refreshSession, requestLoginOtp, verifyLoginOtp } from "./api";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("authentication API", () => {
  beforeEach(() => {
    configureApiAuthentication(undefined);
  });

  it("requests a login OTP without mutating authentication state", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ status: "accepted" }));

    await expect(
      requestLoginOtp("person@example.com"),
    ).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "person@example.com" }),
      }),
    );
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("verifies a login OTP and returns validated session tokens", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        status: "completed",
        access_token: "access-token",
        refresh_token: "refresh-token",
        token_type: "bearer",
        expires_in: 900,
      }),
    );

    await expect(
      verifyLoginOtp("person@example.com", "123456"),
    ).resolves.toEqual({
      accessToken: "access-token",
      refreshToken: "refresh-token",
      tokenType: "bearer",
      expiresIn: 900,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/login/verify",
      expect.objectContaining({
        body: JSON.stringify({ email: "person@example.com", otp: "123456" }),
      }),
    );
    expect(window.sessionStorage.length).toBe(0);
  });

  it("refreshes a session and returns validated rotated tokens", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        access_token: "new-access-token",
        refresh_token: "new-refresh-token",
        token_type: "bearer",
        expires_in: 900,
      }),
    );

    await expect(refreshSession("old-refresh-token")).resolves.toEqual({
      accessToken: "new-access-token",
      refreshToken: "new-refresh-token",
      tokenType: "bearer",
      expiresIn: 900,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/refresh",
      expect.objectContaining({
        body: JSON.stringify({ refresh_token: "old-refresh-token" }),
      }),
    );
  });

  it("fails safely when a token response is malformed", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        status: "completed",
        access_token: "sensitive-access-token",
        refresh_token: "sensitive-refresh-token",
        token_type: "bearer",
      }),
    );

    let thrownError: unknown;
    try {
      await verifyLoginOtp("person@example.com", "123456");
    } catch (error) {
      thrownError = error;
    }

    expect(thrownError).toBeInstanceOf(Error);
    expect(String(thrownError)).toContain(
      "The authentication service returned an invalid response.",
    );
    expect(String(thrownError)).not.toContain("sensitive-access-token");
    expect(String(thrownError)).not.toContain("sensitive-refresh-token");
    expect(window.sessionStorage.length).toBe(0);
  });
});
