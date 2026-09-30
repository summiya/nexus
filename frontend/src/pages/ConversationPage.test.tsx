import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CreatedConversation,
  LiveConversationTurn,
  SubmissionResult,
} from "../features/conversations";

const conversationMocks = vi.hoisted(() => ({
  createConversation: vi.fn(),
  history: vi.fn(),
  historyLiveTurn: vi.fn(),
  historyState: "loaded",
  hookMounts: 0,
  hookUnmounts: 0,
  resetCreation: vi.fn(),
  resetForConversationChange: vi.fn(),
  refetchChatModels: vi.fn(),
  refreshChatModelHook: () => {},
  chatModelsStatus: "success" as "success" | "pending" | "error",
  chatModelsData: {
    items: [
      {
        publicId: "99999999-9999-4999-8999-999999999999",
        displayName: "GPT-5",
        providerType: "openai" as const,
        providerDisplayName: "OpenAI",
      },
      {
        publicId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        displayName: "Claude Sonnet",
        providerType: "anthropic" as const,
        providerDisplayName: "Anthropic",
      },
    ],
    defaultModelPublicId: "99999999-9999-4999-8999-999999999999" as
      string | null,
  },
  liveTurn: null as LiveConversationTurn | null,
  phase: "idle" as "idle" | "submitting" | "generating",
  submit: vi.fn().mockResolvedValue("accepted"),
}));

vi.mock("../features/conversations", async () => {
  const React = await import("react");
  const actual = await vi.importActual<
    typeof import("../features/conversations")
  >("../features/conversations");

  return {
    ...actual,
    ConversationSidebar: () => <aside aria-label="Conversation sidebar" />,
    ConversationMessageHistory: ({
      conversationPublicId,
      liveTurn,
    }: {
      conversationPublicId: string;
      liveTurn?: LiveConversationTurn | null;
    }) => {
      conversationMocks.history(conversationPublicId);
      conversationMocks.historyLiveTurn(liveTurn ?? null);
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
    useCreateConversationMutation: () => {
      const [isPending, setIsPending] = React.useState(false);
      const mutateAsync = React.useCallback(async (input: unknown) => {
        setIsPending(true);
        try {
          return await conversationMocks.createConversation(input);
        } finally {
          setIsPending(false);
        }
      }, []);
      const reset = React.useCallback(() => {
        conversationMocks.resetCreation();
        setIsPending(false);
      }, []);

      return { isPending, mutateAsync, reset };
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
        liveTurn: conversationMocks.liveTurn,
        phase: conversationMocks.phase,
        resetForConversationChange:
          conversationMocks.resetForConversationChange,
        submit: conversationMocks.submit,
      };
    },
    useChatModelsQuery: () => {
      const [, setRevision] = React.useState(0);
      conversationMocks.refreshChatModelHook = () =>
        setRevision((revision) => revision + 1);
      return {
        data:
          conversationMocks.chatModelsStatus === "success"
            ? conversationMocks.chatModelsData
            : undefined,
        isPending: conversationMocks.chatModelsStatus === "pending",
        isError: conversationMocks.chatModelsStatus === "error",
        isSuccess: conversationMocks.chatModelsStatus === "success",
        refetch: conversationMocks.refetchChatModels,
      };
    },
  };
});

import { ConversationPage } from "./ConversationPage";

const firstConversationId = "11111111-1111-4111-8111-111111111111";
const secondConversationId = "22222222-2222-4222-8222-222222222222";
const defaultModelId = "99999999-9999-4999-8999-999999999999";
const alternateModelId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const createdConversation: CreatedConversation = {
  publicId: firstConversationId,
  organizationPublicId: "33333333-3333-4333-8333-333333333333",
  createdByUserPublicId: "44444444-4444-4444-8444-444444444444",
  workspacePublicId: null,
  projectPublicId: null,
  title: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(initialEntry: string, withNavigation = false) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      {withNavigation ? (
        <>
          <Link to={`/conversations/${secondConversationId}`}>
            Open second Conversation
          </Link>
          <Link to="/settings">Leave Conversations</Link>
        </>
      ) : null}
      <LocationProbe />
      <Routes>
        <Route path="/conversations" element={<ConversationPage />} />
        <Route
          path="/conversations/:conversationId"
          element={<ConversationPage />}
        />
        <Route path="/settings" element={<h1>Settings</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversationPage", () => {
  beforeEach(() => {
    conversationMocks.createConversation
      .mockReset()
      .mockResolvedValue(createdConversation);
    conversationMocks.history.mockReset();
    conversationMocks.historyLiveTurn.mockReset();
    conversationMocks.historyState = "loaded";
    conversationMocks.hookMounts = 0;
    conversationMocks.hookUnmounts = 0;
    conversationMocks.resetCreation.mockReset();
    conversationMocks.resetForConversationChange.mockReset();
    conversationMocks.refetchChatModels
      .mockReset()
      .mockResolvedValue(undefined);
    conversationMocks.refreshChatModelHook = () => {};
    conversationMocks.chatModelsStatus = "success";
    conversationMocks.chatModelsData = {
      items: [
        {
          publicId: defaultModelId,
          displayName: "GPT-5",
          providerType: "openai",
          providerDisplayName: "OpenAI",
        },
        {
          publicId: alternateModelId,
          displayName: "Claude Sonnet",
          providerType: "anthropic",
          providerDisplayName: "Anthropic",
        },
      ],
      defaultModelPublicId: defaultModelId,
    };
    conversationMocks.liveTurn = null;
    conversationMocks.phase = "idle";
    conversationMocks.submit.mockReset().mockResolvedValue("accepted");
  });

  it("renders a New Chat composer without creating until valid submission", async () => {
    const user = userEvent.setup();
    renderPage("/conversations");

    expect(
      screen.getByRole("heading", { name: "Start a new conversation" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("message-history")).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Message" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Hello");

    expect(conversationMocks.createConversation).not.toHaveBeenCalled();
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
      screen.getByRole("textbox", { name: "Message" }),
    ).toBeInTheDocument();
  });

  it("submits the selected route ID using server-default model semantics", async () => {
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
    });
    expect(conversationMocks.createConversation).not.toHaveBeenCalled();
  });

  it("submits an explicit model and omits it again after selecting the default", async () => {
    const user = userEvent.setup();
    renderPage(`/conversations/${firstConversationId}`);
    const selector = screen.getByRole("combobox", { name: "Model" });
    const message = screen.getByRole("textbox", { name: "Message" });

    await user.selectOptions(selector, alternateModelId);
    await user.type(message, "Use Claude");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(conversationMocks.submit).toHaveBeenLastCalledWith({
      conversationPublicId: firstConversationId,
      content: "Use Claude",
      modelPublicId: alternateModelId,
    });

    await user.selectOptions(selector, defaultModelId);
    await user.type(message, "Use the default");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(conversationMocks.submit).toHaveBeenLastCalledWith({
      conversationPublicId: firstConversationId,
      content: "Use the default",
    });
  });

  it("requires an explicit choice when no usable default exists", async () => {
    const user = userEvent.setup();
    conversationMocks.chatModelsData = {
      ...conversationMocks.chatModelsData,
      defaultModelPublicId: null,
    };
    renderPage(`/conversations/${firstConversationId}`);

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Choose first",
    );
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Model" }),
      alternateModelId,
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(conversationMocks.submit).toHaveBeenCalledWith({
      conversationPublicId: firstConversationId,
      content: "Choose first",
      modelPublicId: alternateModelId,
    });
  });

  it("blocks submission when no chat model is available", async () => {
    const user = userEvent.setup();
    conversationMocks.chatModelsData = {
      items: [],
      defaultModelPublicId: null,
    };
    renderPage(`/conversations/${firstConversationId}`);

    expect(
      screen.getByText(
        "No chat model is available. Ask an administrator to configure one.",
      ),
    ).toBeVisible();
    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Keep this draft",
    );
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(conversationMocks.submit).not.toHaveBeenCalled();
  });

  it("handles model-query failure with safe retry behavior", async () => {
    const user = userEvent.setup();
    conversationMocks.chatModelsStatus = "error";
    renderPage(`/conversations/${firstConversationId}`);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Chat models are temporarily unavailable.",
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(conversationMocks.refetchChatModels).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it.each(["submitting", "generating"] as const)(
    "disables model selection while %s",
    (phase) => {
      conversationMocks.phase = phase;
      renderPage(`/conversations/${firstConversationId}`);

      expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
    },
  );

  it("clears a stale explicit choice after a successful model refresh", async () => {
    const user = userEvent.setup();
    renderPage(`/conversations/${firstConversationId}`);
    const selector = screen.getByRole("combobox", { name: "Model" });

    await user.selectOptions(selector, alternateModelId);
    expect(selector).toHaveValue(alternateModelId);

    conversationMocks.chatModelsData = {
      items: [conversationMocks.chatModelsData.items[0]],
      defaultModelPublicId: defaultModelId,
    };
    act(() => conversationMocks.refreshChatModelHook());

    await waitFor(() => expect(selector).toHaveValue(defaultModelId));
    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Use refreshed default",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(conversationMocks.submit).toHaveBeenLastCalledWith({
      conversationPublicId: firstConversationId,
      content: "Use refreshed default",
    });
  });

  it("passes the selected Conversation live turn to message history", () => {
    conversationMocks.liveTurn = {
      projectionId: 1,
      conversationPublicId: firstConversationId,
      userContent: "Live question",
      assistantContent: "Live answer",
      generationId: "55555555-5555-4555-8555-555555555555",
      persistedMessagePublicIds: [],
    };

    renderPage(`/conversations/${firstConversationId}`);

    expect(conversationMocks.historyLiveTurn).toHaveBeenCalledWith(
      conversationMocks.liveTurn,
    );
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

  it("keeps the submission owner mounted and resets selected UI on A to B", async () => {
    const user = userEvent.setup();
    renderPage(`/conversations/${firstConversationId}`, true);

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Draft for A",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Model" }),
      alternateModelId,
    );
    await user.click(
      screen.getByRole("link", { name: "Open second Conversation" }),
    );

    expect(screen.getByTestId("message-history")).toHaveTextContent(
      secondConversationId,
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue(
      defaultModelId,
    );
    await waitFor(() =>
      expect(
        conversationMocks.resetForConversationChange,
      ).toHaveBeenCalledOnce(),
    );
    expect(conversationMocks.hookMounts).toBe(1);
    expect(conversationMocks.hookUnmounts).toBe(0);
  });

  it("creates, navigates, and submits the first message without remounting", async () => {
    const user = userEvent.setup();
    renderPage("/conversations");

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "  First message  ",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/conversations/${firstConversationId}`,
      ),
    );
    expect(conversationMocks.createConversation).toHaveBeenCalledOnce();
    expect(conversationMocks.createConversation).toHaveBeenCalledWith(
      undefined,
    );
    expect(conversationMocks.submit).toHaveBeenCalledWith({
      conversationPublicId: firstConversationId,
      content: "First message",
      refreshConversationList: true,
    });
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
    expect(conversationMocks.resetForConversationChange).not.toHaveBeenCalled();
    expect(conversationMocks.hookMounts).toBe(1);
    expect(conversationMocks.hookUnmounts).toBe(0);
  });

  it("uses the model snapshot captured before asynchronous New Chat creation", async () => {
    const user = userEvent.setup();
    const pendingCreation = deferred<CreatedConversation>();
    conversationMocks.createConversation.mockReturnValueOnce(
      pendingCreation.promise,
    );
    renderPage("/conversations");

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Model" }),
      alternateModelId,
    );
    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "First message with Claude",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    conversationMocks.chatModelsData = {
      items: [conversationMocks.chatModelsData.items[0]],
      defaultModelPublicId: defaultModelId,
    };
    act(() => conversationMocks.refreshChatModelHook());

    await act(async () => {
      pendingCreation.resolve(createdConversation);
      await pendingCreation.promise;
    });

    await waitFor(() =>
      expect(conversationMocks.submit).toHaveBeenCalledWith({
        conversationPublicId: firstConversationId,
        content: "First message with Claude",
        modelPublicId: alternateModelId,
        refreshConversationList: true,
      }),
    );
  });

  it("keeps a New Chat live turn through the expected created route transition", async () => {
    const user = userEvent.setup();
    conversationMocks.liveTurn = {
      projectionId: 1,
      conversationPublicId: firstConversationId,
      userContent: "First live message",
      assistantContent: "Streaming response",
      generationId: "55555555-5555-4555-8555-555555555555",
      persistedMessagePublicIds: [],
    };
    renderPage("/conversations");

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "First live message",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/conversations/${firstConversationId}`,
      ),
    );
    expect(conversationMocks.historyLiveTurn).toHaveBeenCalledWith(
      conversationMocks.liveTurn,
    );
    expect(conversationMocks.resetForConversationChange).not.toHaveBeenCalled();
  });

  it("shows creation pending and synchronously prevents duplicate creation", async () => {
    const pendingCreation = deferred<CreatedConversation>();
    conversationMocks.createConversation.mockReturnValueOnce(
      pendingCreation.promise,
    );
    renderPage("/conversations");
    const textarea = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(textarea, { target: { value: "Only once" } });
    const form = textarea.closest("form");
    expect(form).not.toBeNull();

    act(() => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(conversationMocks.createConversation).toHaveBeenCalledOnce();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Creating conversation…",
    );
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();

    await act(async () => {
      pendingCreation.resolve(createdConversation);
      await pendingCreation.promise;
    });
    await waitFor(() =>
      expect(conversationMocks.submit).toHaveBeenCalledOnce(),
    );
  });

  it("keeps the draft and shows safe feedback when creation fails", async () => {
    const user = userEvent.setup();
    conversationMocks.createConversation.mockRejectedValueOnce(
      new Error("private infrastructure detail"),
    );
    renderPage("/conversations");

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Keep this message",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn't confirm the conversation was created. Check your conversations before trying again.",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(
      "private infrastructure detail",
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "Keep this message",
    );
    expect(screen.getByTestId("location")).toHaveTextContent("/conversations");
    expect(conversationMocks.submit).not.toHaveBeenCalled();
  });

  it.each(["uncertain", "not_submitted"] satisfies SubmissionResult[])(
    "keeps the created Conversation and draft when message submission is %s",
    async (result) => {
      const user = userEvent.setup();
      conversationMocks.submit.mockResolvedValueOnce(result);
      renderPage("/conversations");

      await user.type(
        screen.getByRole("textbox", { name: "Message" }),
        "Recoverable draft",
      );
      await user.click(screen.getByRole("button", { name: "Send" }));

      await waitFor(() =>
        expect(screen.getByTestId("location")).toHaveTextContent(
          `/conversations/${firstConversationId}`,
        ),
      );
      expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
        "Recoverable draft",
      );
      expect(conversationMocks.createConversation).toHaveBeenCalledOnce();
    },
  );

  it("ignores a stale creation success after navigation", async () => {
    const user = userEvent.setup();
    const pendingCreation = deferred<CreatedConversation>();
    conversationMocks.createConversation.mockReturnValueOnce(
      pendingCreation.promise,
    );
    renderPage("/conversations", true);

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Old New Chat draft",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(
      screen.getByRole("link", { name: "Open second Conversation" }),
    );

    await act(async () => {
      pendingCreation.resolve(createdConversation);
      await pendingCreation.promise;
    });

    expect(screen.getByTestId("location")).toHaveTextContent(
      `/conversations/${secondConversationId}`,
    );
    expect(conversationMocks.submit).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/couldn't confirm the conversation was created/i),
    ).not.toBeInTheDocument();
  });

  it("ignores a stale creation failure after navigation", async () => {
    const user = userEvent.setup();
    const pendingCreation = deferred<CreatedConversation>();
    conversationMocks.createConversation.mockReturnValueOnce(
      pendingCreation.promise,
    );
    renderPage("/conversations", true);

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Old New Chat draft",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(
      screen.getByRole("link", { name: "Open second Conversation" }),
    );

    await act(async () => {
      pendingCreation.reject(new Error("late creation failure"));
      await pendingCreation.promise.catch(() => undefined);
    });

    expect(screen.getByTestId("location")).toHaveTextContent(
      `/conversations/${secondConversationId}`,
    );
    expect(conversationMocks.submit).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/couldn't confirm the conversation was created/i),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
  });

  it.each(["success", "failure"] as const)(
    "invalidates pending creation on unmount before late %s",
    async (outcome) => {
      const user = userEvent.setup();
      const pendingCreation = deferred<CreatedConversation>();
      conversationMocks.createConversation.mockReturnValueOnce(
        pendingCreation.promise,
      );
      renderPage("/conversations", true);

      await user.type(
        screen.getByRole("textbox", { name: "Message" }),
        "Message from a page we leave",
      );
      await user.click(screen.getByRole("button", { name: "Send" }));
      await user.click(
        screen.getByRole("link", { name: "Leave Conversations" }),
      );

      expect(screen.getByRole("heading", { name: "Settings" })).toBeVisible();
      expect(conversationMocks.hookUnmounts).toBe(1);

      await act(async () => {
        if (outcome === "success") {
          pendingCreation.resolve(createdConversation);
          await pendingCreation.promise;
        } else {
          pendingCreation.reject(new Error("late creation failure"));
          await pendingCreation.promise.catch(() => undefined);
        }
      });

      expect(screen.getByTestId("location")).toHaveTextContent("/settings");
      expect(conversationMocks.submit).not.toHaveBeenCalled();
      expect(
        screen.queryByText(/couldn't confirm the conversation was created/i),
      ).not.toBeInTheDocument();
    },
  );
});
