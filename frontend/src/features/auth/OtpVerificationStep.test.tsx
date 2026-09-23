import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

import { OtpVerificationStep } from "./OtpVerificationStep";

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

function renderStep(overrides?: {
  onVerified?: (tokens: SessionTokens) => void;
  onChangeEmail?: () => void;
}) {
  return render(
    <OtpVerificationStep
      email="person@example.com"
      onVerified={overrides?.onVerified ?? vi.fn()}
      onChangeEmail={overrides?.onChangeEmail ?? vi.fn()}
    />,
  );
}

async function enterOtp(user: ReturnType<typeof userEvent.setup>) {
  await user.type(
    screen.getByRole("textbox", { name: "Verification code" }),
    "123456",
  );
}

describe("OtpVerificationStep", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    apiMocks.requestLoginOtp.mockReset();
    apiMocks.requestLoginOtp.mockResolvedValue(undefined);
    apiMocks.verifyLoginOtp.mockReset();
    apiMocks.verifyLoginOtp.mockResolvedValue(sessionTokens);
  });

  it("uses enumeration-safe confirmation copy", () => {
    renderStep();

    expect(screen.getByRole("status")).toHaveTextContent(
      "If an account exists for this email, a verification code has been sent.",
    );
    expect(screen.queryByText(/account found/i)).not.toBeInTheDocument();
  });

  it("rejects invalid OTP format without verification", async () => {
    const user = userEvent.setup();
    renderStep();

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

  it("returns verified session tokens to the parent", async () => {
    const user = userEvent.setup();
    const onVerified = vi.fn();
    renderStep({ onVerified });
    await enterOtp(user);

    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(apiMocks.verifyLoginOtp).toHaveBeenCalledWith(
      "person@example.com",
      "123456",
    );
    expect(onVerified).toHaveBeenCalledWith(sessionTokens);
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
    renderStep();
    await enterOtp(user);

    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(screen.getByRole("button", { name: "Verifying…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Verifying…" }));

    expect(apiMocks.verifyLoginOtp).toHaveBeenCalledTimes(1);
    resolveVerification?.(sessionTokens);
  });

  it("shows a generic invalid-or-expired message for unauthorized verification", async () => {
    const user = userEvent.setup();
    apiMocks.verifyLoginOtp.mockRejectedValue(
      new NexusApiError("OTP challenge is consumed", 401, "UNAUTHORIZED"),
    );
    renderStep();
    await enterOtp(user);

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
    renderStep();
    await enterOtp(user);

    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Authentication is temporarily unavailable. Please try again.",
    );
    expect(screen.queryByText(/provider database/i)).not.toBeInTheDocument();
  });

  it("resends safely with the same email and prevents duplicate requests", async () => {
    const user = userEvent.setup();
    let resolveResend: (() => void) | undefined;
    apiMocks.requestLoginOtp.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveResend = resolve;
        }),
    );
    renderStep();

    await user.click(screen.getByRole("button", { name: "Resend code" }));
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Sending…" }));

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledTimes(1);
    expect(apiMocks.requestLoginOtp).toHaveBeenCalledWith("person@example.com");
    resolveResend?.();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "If an account exists for this email",
    );
  });

  it("notifies the parent when changing email", async () => {
    const user = userEvent.setup();
    const onChangeEmail = vi.fn();
    renderStep({ onChangeEmail });

    await user.click(screen.getByRole("button", { name: "Change email" }));

    expect(onChangeEmail).toHaveBeenCalledTimes(1);
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
    renderStep();
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
