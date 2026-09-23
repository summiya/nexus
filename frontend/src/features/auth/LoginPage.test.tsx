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

function Destination({ name }: { name: string }) {
  const location = useLocation();
  return (
    <h1>
      {name}: {location.pathname}
      {location.search}
      {location.hash}
    </h1>
  );
}

function renderLogin(from?: string) {
  const initialEntry = from
    ? { pathname: "/login", state: { from } }
    : "/login";
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Destination name="Home" />} />
        <Route path="/settings" element={<Destination name="Settings" />} />
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
    renderLogin();

    expect(
      await screen.findByRole("heading", { name: "Home: /" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });

  it("rejects an invalid email without requesting an OTP", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.type(
      screen.getByRole("textbox", { name: "Email address" }),
      "not-an-email",
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a valid email address.",
    );
    expect(apiMocks.requestLoginOtp).not.toHaveBeenCalled();
  });

  it("requests an OTP with normalized email and advances using enumeration-safe copy", async () => {
    const user = userEvent.setup();
    renderLogin();

    await requestOtp(user);

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledWith("person@example.com");
    expect(screen.getByRole("status")).toHaveTextContent(
      "If an account exists for this email, a verification code has been sent.",
    );
    expect(screen.queryByText(/account found/i)).not.toBeInTheDocument();
  });

  it("prevents duplicate email submissions while the request is pending", async () => {
    const user = userEvent.setup();
    let resolveRequest: (() => void) | undefined;
    apiMocks.requestLoginOtp.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    renderLogin();

    await user.type(
      screen.getByRole("textbox", { name: "Email address" }),
      "person@example.com",
    );
    const continueButton = screen.getByRole("button", { name: "Continue" });
    await user.click(continueButton);
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Sending…" }));

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledTimes(1);
    resolveRequest?.();
    await screen.findByRole("heading", { name: "Check your email" });
  });

  it("shows a safe rate-limit message for an OTP request", async () => {
    const user = userEvent.setup();
    apiMocks.requestLoginOtp.mockRejectedValue(
      new NexusApiError("Request limit exceeded", 429, "RATE_LIMITED"),
    );
    renderLogin();

    await user.type(
      screen.getByRole("textbox", { name: "Email address" }),
      "person@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts. Please try again later.",
    );
    expect(
      screen.queryByText(/request limit exceeded/i),
    ).not.toBeInTheDocument();
  });

  it("rejects invalid OTP format without verification", async () => {
    const user = userEvent.setup();
    renderLogin();
    await requestOtp(user);

    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "12ab",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Verification code must contain digits only.",
    );
    expect(apiMocks.verifyLoginOtp).not.toHaveBeenCalled();
  });

  it("verifies the OTP, establishes the session, and restores the intended route", async () => {
    const user = userEvent.setup();
    renderLogin("/settings?tab=profile#security");
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
    expect(
      await screen.findByRole("heading", {
        name: "Settings: /settings?tab=profile#security",
      }),
    ).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(storedValues(window.sessionStorage)).toContain("refresh-token");
    expect(storedValues(window.sessionStorage)).not.toContain("123456");
  });

  it("prevents duplicate verification while the request is pending", async () => {
    const user = userEvent.setup();
    let resolveVerification: ((tokens: SessionTokens) => void) | undefined;
    apiMocks.verifyLoginOtp.mockImplementation(
      () =>
        new Promise<SessionTokens>((resolve) => {
          resolveVerification = resolve;
        }),
    );
    renderLogin();
    await requestOtp(user);
    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "123456",
    );

    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(screen.getByRole("button", { name: "Verifying…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Verifying…" }));

    expect(apiMocks.verifyLoginOtp).toHaveBeenCalledTimes(1);
    resolveVerification?.(sessionTokens);
    await screen.findByRole("heading", { name: "Home: /" });
  });

  it("falls back to the home route for an unsafe intended destination", async () => {
    const user = userEvent.setup();
    renderLogin("//malicious.example/path");
    await requestOtp(user);
    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(
      await screen.findByRole("heading", { name: "Home: /" }),
    ).toBeInTheDocument();
  });

  it("shows a generic invalid-or-expired message for unauthorized verification", async () => {
    const user = userEvent.setup();
    apiMocks.verifyLoginOtp.mockRejectedValue(
      new NexusApiError("OTP challenge is consumed", 401, "UNAUTHORIZED"),
    );
    renderLogin();
    await requestOtp(user);
    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The verification code is invalid or expired.",
    );
    expect(screen.queryByText(/consumed/i)).not.toBeInTheDocument();
  });

  it("shows a safe temporary message when verification is unavailable", async () => {
    const user = userEvent.setup();
    apiMocks.verifyLoginOtp.mockRejectedValue(
      new NexusApiError(
        "Provider database unavailable",
        503,
        "SERVICE_UNAVAILABLE",
      ),
    );
    renderLogin();
    await requestOtp(user);
    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Authentication is temporarily unavailable. Please try again.",
    );
    expect(screen.queryByText(/provider database/i)).not.toBeInTheDocument();
  });

  it("resends safely with the same email and prevents duplicate requests", async () => {
    const user = userEvent.setup();
    renderLogin();
    await requestOtp(user);
    let resolveResend: (() => void) | undefined;
    apiMocks.requestLoginOtp.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveResend = resolve;
        }),
    );

    await user.click(screen.getByRole("button", { name: "Resend code" }));
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Sending…" }));

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledTimes(2);
    expect(apiMocks.requestLoginOtp).toHaveBeenLastCalledWith(
      "person@example.com",
    );
    resolveResend?.();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "If an account exists for this email",
    );
  });

  it("changes email without retaining OTP or verification errors", async () => {
    const user = userEvent.setup();
    apiMocks.verifyLoginOtp.mockRejectedValue(
      new NexusApiError("Invalid", 401, "UNAUTHORIZED"),
    );
    renderLogin();
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

  it("does not log or persist an unsuccessful OTP", async () => {
    const user = userEvent.setup();
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => {});
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    apiMocks.verifyLoginOtp.mockRejectedValue(
      new NexusApiError("Invalid", 401, "UNAUTHORIZED"),
    );
    renderLogin();
    await requestOtp(user);
    await user.type(
      screen.getByRole("textbox", { name: "Verification code" }),
      "012345",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await screen.findByRole("alert");

    expect(consoleLog).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
    expect(storedValues(window.sessionStorage)).not.toContain("012345");
    expect(storedValues(window.localStorage)).not.toContain("012345");
  });
});
