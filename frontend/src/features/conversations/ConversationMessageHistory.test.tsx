import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NexusApiError } from "../../services/api/error";
import type {
  ConversationGenerationMetadata,
  ConversationMessage,
  ConversationMessageRole,
  GenerationStatus,
} from "./types";

const queryMocks = vi.hoisted(() => ({
  useConversationMessagesQuery: vi.fn(),
}));

vi.mock("./queries", () => queryMocks);

import { ConversationMessageHistory } from "./ConversationMessageHistory";

const conversationPublicId = "11111111-1111-4111-8111-111111111111";

function generation(status: GenerationStatus): ConversationGenerationMetadata {
  return {
    publicId: "22222222-2222-4222-8222-222222222222",
    model: "test-model",
    status,
    finishReason: status === "completed" ? "stop" : null,
    inputTokens: 4,
    outputTokens: 6,
    totalTokens: 10,
    startedAt: "2026-09-23T10:00:00Z",
    completedAt: status === "completed" ? "2026-09-23T10:00:01Z" : null,
    errorKind: status === "failed" ? "private_provider_failure" : null,
  };
}

function message(
  publicId: string,
  role: ConversationMessageRole,
  content: string,
  metadata: ConversationGenerationMetadata | null = null,
): ConversationMessage {
  return {
    publicId,
    role,
    content,
    createdAt: "2026-09-23T10:00:00Z",
    generation: metadata,
  };
}

function queryResult(overrides: Record<string, unknown> = {}) {
  return {
    data: [] as ConversationMessage[],
    error: null,
    isError: false,
    isFetching: false,
    isPending: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

function renderHistory(overrides: Record<string, unknown> = {}) {
  queryMocks.useConversationMessagesQuery.mockReturnValue(
    queryResult(overrides),
  );
  return render(
    <ConversationMessageHistory conversationPublicId={conversationPublicId} />,
  );
}

describe("ConversationMessageHistory", () => {
  beforeEach(() => {
    queryMocks.useConversationMessagesQuery.mockReset();
  });

  it("queries history with the selected Conversation public ID", () => {
    renderHistory();

    expect(queryMocks.useConversationMessagesQuery).toHaveBeenCalledWith(
      conversationPublicId,
    );
  });

  it("announces the loading state", () => {
    renderHistory({ data: undefined, isPending: true });

    expect(screen.getByRole("status")).toHaveTextContent("Loading messages…");
  });

  it("renders a distinct empty state for a selected Conversation", () => {
    renderHistory();

    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
  });

  it("renders all roles in the backend-provided order", () => {
    renderHistory({
      data: [
        message("user-message", "user", "First question"),
        message(
          "assistant-message",
          "assistant",
          "First answer",
          generation("completed"),
        ),
        message("system-message", "system", "System context"),
      ],
    });

    const list = screen.getByRole("list");
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "YouFirst question",
      "NexusFirst answer",
      "SystemSystem context",
    ]);
  });

  it("renders null and completed generation metadata without status chrome", () => {
    renderHistory({
      data: [
        message("user-message", "user", "Question"),
        message(
          "assistant-message",
          "assistant",
          "Answer",
          generation("completed"),
        ),
      ],
    });

    expect(
      screen.queryByText("Response generation failed."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Generation stopped.")).not.toBeInTheDocument();
    expect(screen.queryByText("Generating…")).not.toBeInTheDocument();
  });

  it.each([
    ["failed", "Response generation failed."],
    ["cancelled", "Generation stopped."],
    ["pending", "Generating…"],
    ["running", "Generating…"],
  ] satisfies Array<[GenerationStatus, string]>)(
    "renders a safe %s generation status without internal metadata",
    (status, expectedStatus) => {
      renderHistory({
        data: [
          message(
            "assistant-message",
            "assistant",
            "Persisted response",
            generation(status),
          ),
        ],
      });

      expect(screen.getByText(expectedStatus)).toBeInTheDocument();
      expect(
        screen.queryByText("private_provider_failure"),
      ).not.toBeInTheDocument();
      expect(screen.queryByText("test-model")).not.toBeInTheDocument();
    },
  );

  it("preserves line breaks and renders long HTML-like content as text", () => {
    const longWord = "a".repeat(300);
    const content = `First line\nSecond line <strong>not HTML</strong> ${longWord}`;
    const { container } = renderHistory({
      data: [message("assistant-message", "assistant", content)],
    });

    const contentNode = container.querySelector(
      ".conversation-message-content",
    );
    expect(contentNode).toHaveTextContent("First line");
    expect(contentNode?.textContent).toBe(content);
    expect(contentNode).toHaveTextContent(longWord);
    expect(container.querySelector("strong")).toBeNull();
  });

  it("shows a safe transient error and retries the existing query", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    renderHistory({
      error: new Error("private database failure"),
      isError: true,
      refetch,
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Messages are temporarily unavailable.",
    );
    expect(
      screen.queryByText("private database failure"),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(refetch).toHaveBeenCalledOnce();
  });

  it.each([401, 403, 404, 422])(
    "uses the same safe unavailable state for HTTP %s",
    (status) => {
      renderHistory({
        error: new NexusApiError(
          "sensitive resource detail",
          status,
          "PRIVATE_ERROR",
        ),
        isError: true,
      });

      expect(screen.getByRole("alert")).toHaveTextContent(
        "Conversation unavailable.",
      );
      expect(
        screen.queryByText("sensitive resource detail"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Retry" }),
      ).not.toBeInTheDocument();
    },
  );
});
