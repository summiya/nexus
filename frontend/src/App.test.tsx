import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
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
    vi.spyOn(globalThis, "fetch").mockResolvedValue(conversationListResponse());
  });

  it("redirects the authenticated root to conversations", async () => {
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.location.pathname).toBe("/conversations"),
    );
  });

  it("shows the public product homepage when unauthenticated", async () => {
    authMocks.initializeSession.mockResolvedValue("unauthenticated");
    setAuthStatus("unauthenticated");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: /Every idea.*Every model/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Try the workspace/i }),
    ).toHaveAttribute("href", "/login");
    expect(window.location.pathname).toBe("/");
  });

  it("makes the homepage available to signed-in users through /explore", () => {
    window.history.replaceState({}, "", "/explore");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: /Every idea.*Every model/i }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/explore");
  });

  it("redirects unknown authenticated routes to conversations", async () => {
    window.history.replaceState({}, "", "/does-not-exist");

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.location.pathname).toBe("/conversations"),
    );
  });

  it("redirects the settings index to the Profile section", async () => {
    window.history.replaceState({}, "", "/settings?tab=profile#security");

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Settings" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "Profile" }),
    ).toHaveAttribute("aria-current", "page");
    await waitFor(() =>
      expect(window.location.pathname).toBe("/settings/profile"),
    );
    expect(window.location.search).toBe("?tab=profile");
    expect(window.location.hash).toBe("#security");
  });

  it("routes AI Models inside organization settings", async () => {
    window.history.replaceState({}, "", "/settings/ai-models");
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.endsWith("/model-providers/capabilities")) {
        return Promise.resolve(
          new Response(JSON.stringify({ can_read: false, can_manage: false }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(conversationListResponse());
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "AI Models" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "You do not have permission to view AI model configuration.",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "Settings sections" }))
        .queryByRole("link", { name: "AI Models" }),
    ).not.toBeInTheDocument();
  });

  it("shows a persistent sidebar and removes the old horizontal navigation", () => {
    window.history.replaceState({}, "", "/workspace");
    const { container } = render(<App />);

    expect(
      within(
        screen.getByRole("navigation", { name: "Main navigation" }),
      ).getByRole("link", { name: "Knowledge bases" }),
    ).toHaveAttribute("href", "/knowledge-bases");
    expect(
      within(
        screen.getByRole("navigation", { name: "Main navigation" }),
      ).getByRole("link", { name: "MCP & tools" }),
    ).toHaveAttribute("href", "/tools");
    expect(container.querySelector(".top-bar")).toBeNull();
    expect(
      screen.getAllByRole("button", { name: "Jump to anything" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "Open profile menu" }),
    ).toHaveTextContent("S");
  });

  it("searches the command palette and opens preview destinations", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/workspace");
    render(<App />);

    await user.click(
      screen.getAllByRole("button", { name: "Jump to anything" })[0],
    );
    const dialog = screen.getByRole("dialog", { name: "Jump to anything" });
    await user.type(
      within(dialog).getByRole("textbox", {
        name: "Search NEXUS destinations",
      }),
      "incident",
    );
    await user.click(
      within(dialog).getByRole("option", { name: /Incidents/i }),
    );

    expect(window.location.pathname).toBe("/incidents");
    expect(
      screen.getByRole("heading", { name: "Incidents" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Jump to anything" }),
    ).not.toBeInTheDocument();
  });

  it("opens Profile and Usage from the S account menu", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/workspace");
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Open profile menu" }));
    await user.click(screen.getByRole("menuitem", { name: "Usage" }));

    expect(window.location.pathname).toBe("/settings/usage");
    expect(screen.getByRole("heading", { name: "Usage" })).toBeInTheDocument();
    expect(screen.getByText("No token metering connected")).toBeInTheDocument();
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

  it("renders the new Conversation shell inside the full-viewport authenticated layout", async () => {
    window.history.replaceState({}, "", "/conversations");
    vi.mocked(globalThis.fetch).mockResolvedValue(conversationListResponse());

    const { container } = render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No conversations yet."),
    ).toBeInTheDocument();
    expect(container.querySelector(".app-shell")).toHaveClass(
      "app-shell-conversations",
    );
    expect(container.querySelector(".content-panel")).toHaveClass(
      "content-panel-conversations",
    );
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
    const requestedUrls = vi
      .mocked(globalThis.fetch)
      .mock.calls.map(([input]) =>
        input instanceof Request ? input.url : input.toString(),
      );
    expect(
      requestedUrls.filter((url) =>
        url.endsWith(`/conversations/${conversationId}/messages`),
      ),
    ).toHaveLength(1);
  });

  it("logs out from the main navigation", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/conversations");
    window.sessionStorage.setItem(
      "nexus.authentication.refresh-token",
      "refresh-token",
    );

    render(<App />);

    await user.click(
      within(
        screen.getByRole("navigation", { name: "Main navigation" }),
      ).getByRole("button", { name: "Logout" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/login");
    expect(
      window.sessionStorage.getItem("nexus.authentication.refresh-token"),
    ).toBeNull();
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
});
