import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NexusApiError } from "../../services/api/error";
import type { SessionTokens } from "./types";

const apiMocks = vi.hoisted(() => ({
  requestLoginOtp: vi.fn(),
  verifyLoginOtp: vi.fn(),
}));

vi.mock("./api", () => ({
  requestLoginOtp: apiMocks.requestLoginOtp,
  verifyLoginOtp: apiMocks.verifyLoginOtp,
}));

import { LoginPage } from "./LoginPage";
import { clearSession } from "./session";
import { setAuthStatus, useAuthStore } from "./store";

const sessionTokens: SessionTokens = {
  accessToken: "access-token",
  refreshToken: "refresh-token",
  tokenType: "bearer",
  expiresIn: 900,
};

function storedValues(storage: Storage): string[] {
  return Array.from({ length: storage.length }, (_, index) => {
    const key = storage.key(index);
    return key ? (storage.getItem(key) ?? "") : "";
  });
}

function Destination() {
  const location = useLocation();
  return (
    <p data-testid="destination">
      {location.pathname}
      {location.search}
      {location.hash}
    </p>
  );
}

function renderLoginState(state?: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/login", state }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function requestOtp(user: ReturnType<typeof userEvent.setup>) {
  await user.type(
    screen.getByRole("textbox", { name: "Email address" }),
    " person@example.com ",
  );
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Check your email" });
}

describe("LoginPage", () => {
  beforeEach(() => {
    clearSession();
    setAuthStatus("unauthenticated");
    apiMocks.requestLoginOtp.mockReset();
    apiMocks.requestLoginOtp.mockResolvedValue(undefined);
    apiMocks.verifyLoginOtp.mockReset();
    apiMocks.verifyLoginOtp.mockResolvedValue(sessionTokens);
  });

  it("redirects an authenticated visitor away from login", async () => {
    setAuthStatus("authenticated");
    renderLoginState();

    expect((await screen.findByTestId("destination")).textContent).toBe("/");
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });

  it.each([
    ["home", "/"],
    ["settings", "/settings"],
    ["settings with query and hash", "/settings?tab=profile#security"],
    ["similarly named login history", "/login-history"],
    ["similarly named login settings", "/login-settings"],
  ])("preserves the valid internal %s destination", async (_name, from) => {
    setAuthStatus("authenticated");
    renderLoginState({ from });

    expect((await screen.findByTestId("destination")).textContent).toBe(from);
  });

  it.each([
    ["protocol-relative URL", { from: "//evil.com" }],
    ["backslash-based URL", { from: "/\\evil.com" }],
    ["absolute URL", { from: "https://evil.com" }],
    ["JavaScript URL", { from: "javascript:alert(1)" }],
    ["empty destination", { from: "" }],
    ["non-string destination", { from: 42 }],
    ["missing destination", {}],
    ["non-object state", "invalid"],
    ["null state", null],
    ["login", { from: "/login" }],
    ["login with trailing slash", { from: "/login/" }],
    ["login with query", { from: "/login?x=1" }],
    ["login with hash", { from: "/login#section" }],
    ["uppercase login", { from: "/LOGIN" }],
    ["mixed-case login", { from: "/Login/" }],
  ])("falls back to home for a %s", async (_name, state) => {
    setAuthStatus("authenticated");
    renderLoginState(state);

    expect((await screen.findByTestId("destination")).textContent).toBe("/");
  });

  it("advances from email request to OTP verification", async () => {
    const user = userEvent.setup();
    renderLoginState();

    await requestOtp(user);

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledWith("person@example.com");
    expect(screen.getByText("person@example.com")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "If an account exists for this email, a verification code has been sent.",
    );
  });

  it("establishes the session and restores the intended route", async () => {
    const user = userEvent.setup();
    renderLoginState({ from: "/settings?tab=profile#security" });
    await requestOtp(user);

    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(apiMocks.verifyLoginOtp).toHaveBeenCalledWith(
      "person@example.com",
      "123456",
    );
    expect((await screen.findByTestId("destination")).textContent).toBe(
      "/settings?tab=profile#security",
    );
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(storedValues(window.sessionStorage)).toContain("refresh-token");
    expect(storedValues(window.sessionStorage)).not.toContain("123456");
  });

  it("preserves the email while clearing OTP state when changing steps", async () => {
    const user = userEvent.setup();
    apiMocks.verifyLoginOtp.mockRejectedValue(
      new NexusApiError("Invalid", 401, "UNAUTHORIZED"),
    );
    renderLoginState();
    await requestOtp(user);
    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await screen.findByRole("alert");

    await user.click(screen.getByRole("button", { name: "Change email" }));

    expect(screen.getByRole("textbox", { name: "Email address" })).toHaveValue(
      "person@example.com",
    );
    expect(screen.queryByText(/invalid or expired/i)).not.toBeInTheDocument();

    apiMocks.verifyLoginOtp.mockResolvedValue(sessionTokens);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByRole("textbox", { name: "Verification code" }),
    ).toHaveValue("");
  });
});
