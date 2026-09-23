import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NexusApiError } from "../../services/api/error";

const apiMocks = vi.hoisted(() => ({
  requestLoginOtp: vi.fn(),
}));

vi.mock("./api", () => ({
  requestLoginOtp: apiMocks.requestLoginOtp,
}));

import { EmailLoginStep } from "./EmailLoginStep";

describe("EmailLoginStep", () => {
  beforeEach(() => {
    apiMocks.requestLoginOtp.mockReset();
    apiMocks.requestLoginOtp.mockResolvedValue(undefined);
  });

  it("rejects an invalid email without requesting an OTP", async () => {
    const user = userEvent.setup();
    render(<EmailLoginStep initialEmail="" onOtpRequested={vi.fn()} />);

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

  it("requests an OTP with the normalized email", async () => {
    const user = userEvent.setup();
    const onOtpRequested = vi.fn();
    render(<EmailLoginStep initialEmail="" onOtpRequested={onOtpRequested} />);

    await user.type(
      screen.getByRole("textbox", { name: "Email address" }),
      " person@example.com ",
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledWith("person@example.com");
    expect(onOtpRequested).toHaveBeenCalledWith("person@example.com");
  });

  it("prevents duplicate submissions while the request is pending", async () => {
    const user = userEvent.setup();
    let resolveRequest: (() => void) | undefined;
    apiMocks.requestLoginOtp.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    render(<EmailLoginStep initialEmail="" onOtpRequested={vi.fn()} />);

    await user.type(
      screen.getByRole("textbox", { name: "Email address" }),
      "person@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Sending…" }));

    expect(apiMocks.requestLoginOtp).toHaveBeenCalledTimes(1);
    resolveRequest?.();
  });

  it("shows a safe rate-limit message", async () => {
    const user = userEvent.setup();
    apiMocks.requestLoginOtp.mockRejectedValue(
      new NexusApiError("Request limit exceeded", 429, "RATE_LIMITED"),
    );
    render(<EmailLoginStep initialEmail="" onOtpRequested={vi.fn()} />);

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
});
