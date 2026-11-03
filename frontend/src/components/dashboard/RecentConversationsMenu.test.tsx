import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationSummary } from "../../features/conversations/types";

const queryMocks = vi.hoisted(() => ({
  useConversationsQuery: vi.fn(),
}));

vi.mock("../../features/conversations/queries", () => queryMocks);

import { RecentConversationsMenu } from "./RecentConversationsMenu";

const sampleChats: ConversationSummary[] = Array.from(
  { length: 7 },
  (_, index) => ({
    publicId: "00000000-0000-4000-8000-" + String(index + 1).padStart(12, "0"),
    title: index === 2 ? null : "Chat " + (index + 1),
    createdAt: "2026-11-01T09:00:00Z",
    updatedAt: "2026-11-" + String(index + 1).padStart(2, "0") + "T09:00:00Z",
  }),
);

function queryResult(overrides: Record<string, unknown> = {}) {
  return {
    data: sampleChats,
    isPending: false,
    isSuccess: true,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="current-location">{location.pathname}</span>;
}

function renderRecent(initialPath = "/conversations", closeSidebar = vi.fn()) {
  return {
    closeSidebar,
    ...render(
      <MemoryRouter initialEntries={[initialPath]}>
        <RecentConversationsMenu closeSidebar={closeSidebar} />
        <LocationProbe />
      </MemoryRouter>,
    ),
  };
}

describe("RecentConversationsMenu", () => {
  beforeEach(() => {
    queryMocks.useConversationsQuery.mockReset();
    queryMocks.useConversationsQuery.mockReturnValue(queryResult());
  });

  it("lists the newest chats first in a five-row scroll region", () => {
    renderRecent();

    const recent = screen.getByRole("navigation", {
      name: "Recent chat list",
    });
    expect(recent).toHaveClass("nx-dash-recents-scroll");

    const links = within(recent).getAllByRole("link");
    expect(links).toHaveLength(7);
    expect(
      links.map((link) =>
        link.querySelector(".nx-dash-recent-chat-title")?.textContent,
      ),
    ).toEqual([
      "Chat 7",
      "Chat 6",
      "Chat 5",
      "Chat 4",
      "New conversation",
      "Chat 2",
      "Chat 1",
    ]);

    expect(screen.getByText("RECENT CHATS")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New chat" })).toHaveAttribute(
      "href",
      "/conversations",
    );
  });

  it("opens the selected real conversation in the existing route", async () => {
    const user = userEvent.setup();
    const closeSidebar = vi.fn();
    renderRecent("/conversations", closeSidebar);

    await user.click(screen.getByRole("link", { name: "Chat 7" }));

    expect(screen.getByTestId("current-location")).toHaveTextContent(
      "/conversations/00000000-0000-4000-8000-000000000007",
    );
    expect(screen.getByRole("link", { name: "Chat 7" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Chat 7" })).not.toHaveAttribute(
      "target",
    );
    expect(closeSidebar).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("link", { name: "New chat" }));
    expect(screen.getByTestId("current-location")).toHaveTextContent(
      "/conversations",
    );
  });

  it("keeps new chat available when there is no history", () => {
    queryMocks.useConversationsQuery.mockReturnValue(queryResult({ data: [] }));
    renderRecent();

    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New chat" })).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Recent chat list" }),
    ).not.toBeInTheDocument();
  });

  it("reports loading and retryable errors without exposing backend details", async () => {
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({ data: undefined, isPending: true, isSuccess: false }),
    );
    const { rerender } = renderRecent();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading recent chats",
    );

    const refetch = vi.fn();
    queryMocks.useConversationsQuery.mockReturnValue(
      queryResult({
        data: undefined,
        isPending: false,
        isSuccess: false,
        isError: true,
        error: new Error("private backend details"),
        refetch,
      }),
    );

    rerender(
      <MemoryRouter>
        <RecentConversationsMenu closeSidebar={vi.fn()} />
        <LocationProbe />
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Chats are temporarily unavailable.",
    );
    expect(
      screen.queryByText("private backend details"),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
