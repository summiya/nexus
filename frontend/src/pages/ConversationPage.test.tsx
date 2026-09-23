import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const conversationMocks = vi.hoisted(() => ({
  history: vi.fn(),
  historyState: "loaded",
}));

vi.mock("../features/conversations", () => ({
  ConversationSidebar: () => <aside aria-label="Conversation sidebar" />,
  ConversationMessageHistory: ({
    conversationPublicId,
  }: {
    conversationPublicId: string;
  }) => {
    conversationMocks.history(conversationPublicId);
    if (conversationMocks.historyState === "loading") {
      return <p role="status">Loading messages…</p>;
    }
    if (conversationMocks.historyState === "error") {
      return <p role="alert">Messages are temporarily unavailable.</p>;
    }
    return (
      <div data-testid="message-history">
        History for {conversationPublicId}
      </div>
    );
  },
}));

import { ConversationPage } from "./ConversationPage";

const firstConversationId = "11111111-1111-4111-8111-111111111111";
const secondConversationId = "22222222-2222-4222-8222-222222222222";

function renderPage(initialEntry: string, withNavigation = false) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      {withNavigation ? (
        <Link to={`/conversations/${secondConversationId}`}>
          Open second Conversation
        </Link>
      ) : null}
      <Routes>
        <Route path="/conversations" element={<ConversationPage />} />
        <Route
          path="/conversations/:conversationId"
          element={<ConversationPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversationPage", () => {
  beforeEach(() => {
    conversationMocks.history.mockReset();
    conversationMocks.historyState = "loaded";
  });

  it("keeps the New Chat placeholder and does not render history", () => {
    renderPage("/conversations");

    expect(
      screen.getByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("message-history")).not.toBeInTheDocument();
    expect(conversationMocks.history).not.toHaveBeenCalled();
  });

  it("renders selected history using the route ID alongside the sidebar", () => {
    renderPage(`/conversations/${firstConversationId}`);

    expect(screen.getByTestId("message-history")).toHaveTextContent(
      firstConversationId,
    );
    expect(conversationMocks.history).toHaveBeenCalledWith(firstConversationId);
    expect(
      screen.getByRole("complementary", { name: "Conversation sidebar" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["loading", "status"],
    ["error", "alert"],
  ])("keeps the sidebar rendered during a history %s state", (state, role) => {
    conversationMocks.historyState = state;
    renderPage(`/conversations/${firstConversationId}`);

    expect(screen.getByRole(role)).toBeInTheDocument();
    expect(
      screen.getByRole("complementary", { name: "Conversation sidebar" }),
    ).toBeInTheDocument();
  });

  it("renders the newly selected Conversation after a route change", async () => {
    const user = userEvent.setup();
    renderPage(`/conversations/${firstConversationId}`, true);

    await user.click(
      screen.getByRole("link", { name: "Open second Conversation" }),
    );

    expect(screen.getByTestId("message-history")).toHaveTextContent(
      secondConversationId,
    );
    expect(conversationMocks.history).toHaveBeenLastCalledWith(
      secondConversationId,
    );
  });
});
