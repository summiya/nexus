import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sessionMocks = vi.hoisted(() => ({
  initializeSession: vi.fn(),
}));

vi.mock("./session", () => sessionMocks);

import { AuthStatusView } from "./AuthStatusView";

describe("AuthStatusView", () => {
  beforeEach(() => {
    sessionMocks.initializeSession.mockReset();
    sessionMocks.initializeSession.mockResolvedValue("authenticated");
  });

  it("shows the session restoration state while initializing", () => {
    render(<AuthStatusView status="initializing" />);

    expect(
      screen.getByRole("heading", { name: "Restoring your session" }),
    ).toBeInTheDocument();
  });

  it("shows the unavailable state and retries session restoration", async () => {
    const user = userEvent.setup();
    render(<AuthStatusView status="unavailable" />);

    expect(
      screen.getByRole("heading", {
        name: "Session temporarily unavailable",
      }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(sessionMocks.initializeSession).toHaveBeenCalledTimes(1);
  });
});
