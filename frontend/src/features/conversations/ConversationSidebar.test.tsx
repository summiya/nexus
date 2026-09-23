import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationSummary } from "./types";

const queryMocks = vi.hoisted(() => ({
  useConversationsQuery: vi.fn(),
}));

vi.mock("./queries", () => queryMocks);

import { ConversationSidebar } from "./ConversationSidebar";

const firstConversation: ConversationSummary = {
  publicId: "11111111-1111-4111-8111-111111111111",
  title: "Architecture notes",
  createdAt: "2026-09-23T10:00:00Z",
  updatedAt: "2026-09-23T10:30:00Z",
};

const secondConversation: ConversationSummary = {
  publicId: "22222222-2222-4222-8222-222222222222",
  title: "Release planning",
  createdAt: "2026-09-23T09:00:00Z",
  updatedAt: "2026-09-23T09:30:00Z",
};

const untitledConversation: ConversationSummary = {
  publicId: "33333333-3333-4333-8333-333333333333",
  title: null,
  createdAt: "2026-09-23T08:00:00Z",
  updatedAt: "2026-09-23T08:30:00Z",
};

function LocationView() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

function renderSidebar(initialEntry = "/conversations") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ConversationSidebar />
      <LocationView />
    </MemoryRouter>,
  );
}

function queryResult(overrides: Record<string, unknown> = {}) {
  return {
    data: [] as ConversationSummary[],
    isError: false,
    isFetching: false,
    isPending: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("ConversationSidebar", () => {
  beforeEach(() => {
    queryMocks.useConversationsQuery.mockReset();
    queryMocks.useConversationsQuery.mockReturnValue(queryResult());
  });

  it("announces the loading state", () => {
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({ data: undefined, isPending: true }),
    );

    renderSidebar();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading conversations",
    );
    expect(screen.getByRole("link", { name: "New chat" })).toBeInTheDocument();
  });

  it("renders titles in backend order and falls back only for a null title", () => {
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({
        data: [firstConversation, secondConversation, untitledConversation],
      }),
    );

    renderSidebar();

    const navigation = screen.getByRole("navigation", {
      name: "Conversation list",
    });
    expect(
      within(navigation)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Architecture notes", "Release planning", "New conversation"]);
  });

  it("shows an empty state without removing New chat", () => {
    renderSidebar();

    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New chat" })).toBeInTheDocument();
  });

  it("shows a safe error and retries without exposing the source error", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        refetch,
        error: new Error("private backend details"),
      }),
    );

    renderSidebar();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Conversations are temporarily unavailable.",
    );
    expect(
      screen.queryByText("private backend details"),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(refetch).toHaveBeenCalledOnce();
  });

  it("derives the selected Conversation from the current route", () => {
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({ data: [firstConversation, secondConversation] }),
    );

    renderSidebar(`/conversations/${secondConversation.publicId}`);

    expect(
      screen.getByRole("link", { name: "Release planning" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Architecture notes" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("navigates to the selected Conversation", async () => {
    const user = userEvent.setup();
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({ data: [firstConversation] }),
    );
    renderSidebar();

    await user.click(screen.getByRole("link", { name: "Architecture notes" }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      `/conversations/${firstConversation.publicId}`,
    );
  });

  it("navigates New chat locally without making a backend request", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({ data: [firstConversation] }),
    );
    renderSidebar(`/conversations/${firstConversation.publicId}`);

    await user.click(screen.getByRole("link", { name: "New chat" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/conversations");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
