import { render, screen } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authMocks = vi.hoisted(() => ({
  initializeSession: vi.fn(),
}));

vi.mock("./features/auth", async () => {
  const actual =
    await vi.importActual<typeof import("./features/auth")>("./features/auth");
  return { ...actual, initializeSession: authMocks.initializeSession };
});

vi.mock("./lib/query-client", () => ({
  createQueryClient: () =>
    new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          refetchOnWindowFocus: false,
          staleTime: 0,
        },
      },
    }),
}));

import App from "./App";
import { setAuthStatus } from "./features/auth/store";

describe("App", () => {
  beforeEach(() => {
    authMocks.initializeSession.mockReset();
    authMocks.initializeSession.mockResolvedValue("authenticated");
    setAuthStatus("authenticated");
    window.history.replaceState({}, "", "/");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("renders the application through the provider and router composition", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Application foundation" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
  });

  it("redirects unknown routes to the home page", async () => {
    window.history.replaceState({}, "", "/does-not-exist");

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Application foundation" }),
    ).toBeInTheDocument();
  });

  it("renders the settings route inside the application shell", async () => {
    window.history.replaceState({}, "", "/settings");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Foundation configuration" }),
    ).toBeInTheDocument();
  });

  it("shows the API error state when backend health fails", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({ error: { message: "Backend unavailable" } }),
        {
          status: 503,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    render(<App />);

    expect(await screen.findByText("Unhealthy")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Backend unavailable");
  });
});
