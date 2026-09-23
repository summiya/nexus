import {
  skipToken,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createConversation,
  getConversationMessages,
  listConversations,
} from "./api";

export const conversationKeys = {
  all: ["conversations"] as const,
  list: () => ["conversations", "list"] as const,
  messages: (conversationPublicId: string) =>
    ["conversations", "messages", conversationPublicId] as const,
};

function normalizeConversationPublicId(
  conversationPublicId: string | null | undefined,
): string | null {
  const normalized = conversationPublicId?.trim();
  return normalized ? normalized : null;
}

export function useConversationsQuery() {
  return useQuery({
    queryKey: conversationKeys.list(),
    queryFn: listConversations,
  });
}

export function useConversationMessagesQuery(
  conversationPublicId: string | null | undefined,
) {
  const normalizedId = normalizeConversationPublicId(conversationPublicId);

  return useQuery({
    queryKey: conversationKeys.messages(normalizedId ?? ""),
    queryFn:
      normalizedId === null
        ? skipToken
        : () => getConversationMessages(normalizedId),
    enabled: normalizedId !== null,
  });
}

export function useCreateConversationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createConversation,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: conversationKeys.list() }),
  });
}
