import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sessionMocks = vi.hoisted(() => ({
  initializeSession: vi.fn(),
}));

vi.mock("./session", () => sessionMocks);

import { AuthGate } from "./AuthGate";
import { setAuthStatus } from "./store";

function LoginDestination() {
  const location = useLocation();
  const state = location.state as { from?: string } | null;
  return <p>Login destination: {state?.from ?? "none"}</p>;
}

function renderProtectedRoute(initialEntry = "/settings?tab=profile#details") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginDestination />} />
        <Route element={<AuthGate />}>
          <Route path="/settings" element={<h1>Protected settings</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthGate", () => {
  beforeEach(() => {
    sessionMocks.initializeSession.mockReset();
    sessionMocks.initializeSession.mockResolvedValue("authenticated");
    setAuthStatus("initializing");
  });

  it("shows session restoration without redirecting while initializing", () => {
    renderProtectedRoute();

    expect(
      screen.getByRole("heading", { name: "Restoring your session" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Login destination/)).not.toBeInTheDocument();
  });

  it("redirects an unauthenticated protected route and preserves its internal location", async () => {
    setAuthStatus("unauthenticated");
    renderProtectedRoute();

    expect(
      await screen.findByText(
        "Login destination: /settings?tab=profile#details",
      ),
    ).toBeInTheDocument();
  });

  it("renders the protected application for an authenticated session", () => {
    setAuthStatus("authenticated");
    renderProtectedRoute();

    expect(
      screen.getByRole("heading", { name: "Protected settings" }),
    ).toBeInTheDocument();
  });

  it("shows a retryable recovery state when restoration is unavailable", async () => {
    const user = userEvent.setup();
    setAuthStatus("unavailable");
    renderProtectedRoute();

    expect(
      screen.getByRole("heading", {
        name: "Session temporarily unavailable",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Login destination/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(sessionMocks.initializeSession).toHaveBeenCalledTimes(1);
  });
});
