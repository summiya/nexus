import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const conversationMocks = vi.hoisted(() => ({
  history: vi.fn(),
  historyState: "loaded",
  hookMounts: 0,
  hookUnmounts: 0,
  resetForConversationChange: vi.fn(),
  submit: vi.fn().mockResolvedValue("accepted"),
}));

vi.mock("../features/conversations", async () => {
  const React = await import("react");

  return {
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
    ConversationComposer: ({
      onSubmit,
    }: {
      onSubmit: (content: string) => Promise<string>;
    }) => {
      const [draft, setDraft] = React.useState("");
      return (
        <form
          aria-label="Conversation composer"
          onSubmit={(event) => {
            event.preventDefault();
            void onSubmit(draft);
          }}
        >
          <label htmlFor="page-test-message">Message</label>
          <textarea
            id="page-test-message"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit">Send</button>
        </form>
      );
    },
    useConversationSubmission: () => {
      React.useEffect(() => {
        conversationMocks.hookMounts += 1;
        return () => {
          conversationMocks.hookUnmounts += 1;
        };
      }, []);
      return {
        feedback: null,
        phase: "idle",
        resetForConversationChange:
          conversationMocks.resetForConversationChange,
        submit: conversationMocks.submit,
      };
    },
  };
});

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
    conversationMocks.hookMounts = 0;
    conversationMocks.hookUnmounts = 0;
    conversationMocks.resetForConversationChange.mockReset();
    conversationMocks.submit.mockReset().mockResolvedValue("accepted");
  });

  it("keeps the New Chat placeholder without history or a composer", () => {
    renderPage("/conversations");

    expect(
      screen.getByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("message-history")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Conversation composer" }),
    ).not.toBeInTheDocument();
    expect(conversationMocks.history).not.toHaveBeenCalled();
  });

  it("renders selected history and the composer alongside the sidebar", () => {
    renderPage(`/conversations/${firstConversationId}`);

    expect(screen.getByTestId("message-history")).toHaveTextContent(
      firstConversationId,
    );
    expect(conversationMocks.history).toHaveBeenCalledWith(firstConversationId);
    expect(
      screen.getByRole("complementary", { name: "Conversation sidebar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("form", { name: "Conversation composer" }),
    ).toBeInTheDocument();
  });

  it("submits the selected route ID and configured model", async () => {
    const user = userEvent.setup();
    renderPage(`/conversations/${firstConversationId}`);

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Explain streams",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(conversationMocks.submit).toHaveBeenCalledWith({
      conversationPublicId: firstConversationId,
      content: "Explain streams",
      model: "gpt-4o-mini",
    });
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

  it("keeps the submission owner mounted and resets only selected UI on A to B", async () => {
    const user = userEvent.setup();
    renderPage(`/conversations/${firstConversationId}`, true);

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Draft for A",
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "Draft for A",
    );

    await user.click(
      screen.getByRole("link", { name: "Open second Conversation" }),
    );

    expect(screen.getByTestId("message-history")).toHaveTextContent(
      secondConversationId,
    );
    expect(conversationMocks.history).toHaveBeenLastCalledWith(
      secondConversationId,
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
    await waitFor(() =>
      expect(
        conversationMocks.resetForConversationChange,
      ).toHaveBeenCalledOnce(),
    );
    expect(conversationMocks.hookMounts).toBe(1);
    expect(conversationMocks.hookUnmounts).toBe(0);
  });
});
