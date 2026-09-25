import { render, screen, within } from "@testing-library/react";
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

const conversationId = "11111111-1111-4111-8111-111111111111";

function conversationListResponse(): Response {
  return new Response(JSON.stringify({ items: [] }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function unavailableConversationResponse(): Response {
  return new Response(
    JSON.stringify({
      error: {
        code: "NOT_FOUND",
        message: "private resource detail",
      },
    }),
    {
      status: 404,
      headers: { "Content-Type": "application/json" },
    },
  );
}

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

  it("renders the Files route inside the authenticated application shell", () => {
    window.history.replaceState({}, "", "/files");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Upload a file" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Maximum file size: 512 MB.")).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("navigation", { name: "Main navigation" }),
      ).getByRole("link", { name: "Files" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("keeps the Files route behind the existing authentication gate", async () => {
    setAuthStatus("unauthenticated");
    window.history.replaceState({}, "", "/files");

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Upload a file" }),
    ).not.toBeInTheDocument();
  });

  it("renders the new Conversation shell inside the authenticated layout", async () => {
    window.history.replaceState({}, "", "/conversations");
    vi.mocked(globalThis.fetch).mockResolvedValue(conversationListResponse());

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No conversations yet."),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("navigation", { name: "Main navigation" }),
      ).getByRole("link", { name: "Conversations" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("lets the history API determine whether a stale Conversation is available", async () => {
    window.history.replaceState({}, "", `/conversations/${conversationId}`);
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = input instanceof Request ? input.url : input.toString();
      return Promise.resolve(
        url.endsWith(`/conversations/${conversationId}/messages`)
          ? unavailableConversationResponse()
          : conversationListResponse(),
      );
    });

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Conversation unavailable.",
    );
    expect(
      screen.queryByText("private resource detail"),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByText("No conversations yet."),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe(`/conversations/${conversationId}`);
    expect(
      within(
        screen.getByRole("navigation", { name: "Main navigation" }),
      ).getByRole("link", { name: "Conversations" }),
    ).toHaveAttribute("aria-current", "page");
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps Conversation routes behind the existing authentication gate", async () => {
    setAuthStatus("unauthenticated");
    window.history.replaceState({}, "", "/conversations");

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Start a new conversation" }),
    ).not.toBeInTheDocument();
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
