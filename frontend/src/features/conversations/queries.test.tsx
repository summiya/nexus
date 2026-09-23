import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationSummary, CreatedConversation } from "./types";

const apiMocks = vi.hoisted(() => ({
  createConversation: vi.fn(),
  getConversationMessages: vi.fn(),
  listConversations: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

import {
  conversationKeys,
  useConversationMessagesQuery,
  useConversationsQuery,
  useCreateConversationMutation,
} from "./queries";

const conversationId = "11111111-1111-4111-8111-111111111111";
const secondConversationId = "22222222-2222-4222-8222-222222222222";

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function wrapper(queryClient: QueryClient) {
  return function TestQueryClientProvider({
    children,
  }: {
    children: ReactNode;
  }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("Conversation queries", () => {
  beforeEach(() => {
    apiMocks.createConversation.mockReset();
    apiMocks.getConversationMessages.mockReset();
    apiMocks.listConversations.mockReset();
  });

  it("defines stable feature, list, and conversation-scoped message keys", () => {
    expect(conversationKeys.all).toEqual(["conversations"]);
    expect(conversationKeys.list()).toEqual(["conversations", "list"]);
    expect(conversationKeys.messages(conversationId)).toEqual([
      "conversations",
      "messages",
      conversationId,
    ]);
    expect(conversationKeys.messages(secondConversationId)).not.toEqual(
      conversationKeys.messages(conversationId),
    );
  });

  it("wires the list hook to the Conversation API", async () => {
    const conversations: ConversationSummary[] = [
      {
        publicId: conversationId,
        title: "Architecture",
        createdAt: "2026-09-23T08:30:00Z",
        updatedAt: "2026-09-23T09:30:00Z",
      },
    ];
    apiMocks.listConversations.mockResolvedValue(conversations);
    const queryClient = createTestQueryClient();
    const { result } = renderHook(() => useConversationsQuery(), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.data).toEqual(conversations));

    expect(apiMocks.listConversations).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(conversationKeys.list())).toEqual(
      conversations,
    );
  });

  it.each([null, undefined, "", "   "])(
    "disables the message query without a usable ID (%s)",
    async (unusableId) => {
      const queryClient = createTestQueryClient();
      const { result } = renderHook(
        () => useConversationMessagesQuery(unusableId),
        { wrapper: wrapper(queryClient) },
      );

      await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));

      expect(result.current.status).toBe("pending");
      expect(apiMocks.getConversationMessages).not.toHaveBeenCalled();
      expect(
        queryClient.getQueryCache().find({
          queryKey: conversationKeys.messages(""),
        }),
      ).toBeDefined();
    },
  );

  it("uses the normalized ID for both the message key and request", async () => {
    apiMocks.getConversationMessages.mockResolvedValue([]);
    const queryClient = createTestQueryClient();
    const { result } = renderHook(
      () => useConversationMessagesQuery(`  ${conversationId}  `),
      { wrapper: wrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(apiMocks.getConversationMessages).toHaveBeenCalledWith(
      conversationId,
    );
    expect(
      queryClient.getQueryData(conversationKeys.messages(conversationId)),
    ).toEqual([]);
    expect(
      queryClient.getQueryCache().find({
        queryKey: conversationKeys.messages(`  ${conversationId}  `),
      }),
    ).toBeUndefined();
  });

  it("returns the created Conversation and invalidates the list", async () => {
    const createdConversation: CreatedConversation = {
      publicId: conversationId,
      organizationPublicId: "33333333-3333-4333-8333-333333333333",
      createdByUserPublicId: "44444444-4444-4444-8444-444444444444",
      workspacePublicId: null,
      projectPublicId: null,
      title: "New conversation",
    };
    apiMocks.createConversation.mockResolvedValue(createdConversation);
    const queryClient = createTestQueryClient();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderHook(() => useCreateConversationMutation(), {
      wrapper: wrapper(queryClient),
    });

    let mutationResult: CreatedConversation | undefined;
    await act(async () => {
      mutationResult = await result.current.mutateAsync({
        title: "New conversation",
      });
    });

    expect(apiMocks.createConversation.mock.calls[0][0]).toEqual({
      title: "New conversation",
    });
    expect(mutationResult).toEqual(createdConversation);
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: conversationKeys.list(),
    });
  });
});
