import { NexusApiError } from "../../services/api/error";
import { useConversationMessagesQuery } from "./queries";
import type { LiveConversationTurn } from "./useConversationSubmission";
import type { ConversationMessageRole, GenerationStatus } from "./types";

interface ConversationMessageHistoryProps {
  conversationPublicId: string;
  liveTurn?: LiveConversationTurn | null;
}

const roleLabels: Record<ConversationMessageRole, string> = {
  user: "You",
  assistant: "Nexus",
  system: "System",
};

const unavailableStatuses = new Set([401, 403, 404, 422]);

function conversationIsUnavailable(error: unknown): boolean {
  return (
    error instanceof NexusApiError && unavailableStatuses.has(error.status)
  );
}

function generationStatusMessage(status: GenerationStatus): string | null {
  switch (status) {
    case "failed":
      return "Response generation failed.";
    case "cancelled":
      return "Generation stopped.";
    case "pending":
    case "running":
      return "Generating…";
    case "completed":
      return null;
  }
}

function ConversationMessageItem({
  content,
  generationStatus,
  live = false,
  role,
}: {
  content: string;
  generationStatus: GenerationStatus | null;
  live?: boolean;
  role: ConversationMessageRole;
}) {
  const statusMessage = generationStatus
    ? generationStatusMessage(generationStatus)
    : null;
  const generationIsActive =
    generationStatus === "pending" || generationStatus === "running";

  return (
    <li
      className={`conversation-message conversation-message-${role}${live ? " conversation-message-live" : ""}`}
    >
      <article>
        <p className="conversation-message-role">{roleLabels[role]}</p>
        <p className="conversation-message-content">{content}</p>
        {statusMessage ? (
          <p
            className={`conversation-generation-status conversation-generation-status-${generationStatus}`}
            role={generationIsActive ? "status" : undefined}
          >
            {statusMessage}
          </p>
        ) : null}
      </article>
    </li>
  );
}

export function ConversationMessageHistory({
  conversationPublicId,
  liveTurn = null,
}: ConversationMessageHistoryProps) {
  const messages = useConversationMessagesQuery(conversationPublicId);
  const activeLiveTurn =
    liveTurn?.conversationPublicId === conversationPublicId ? liveTurn : null;
  const persistedMessages = messages.data ?? [];
  const baselineIsKnown =
    activeLiveTurn !== null &&
    activeLiveTurn.persistedMessagePublicIds !== null;
  const baselineMessagePublicIds = new Set(
    activeLiveTurn?.persistedMessagePublicIds ?? [],
  );
  const messagesPersistedSinceSubmission = baselineIsKnown
    ? persistedMessages.filter(
        (message) => !baselineMessagePublicIds.has(message.publicId),
      )
    : [];
  const userProjectionPersisted =
    activeLiveTurn !== null &&
    messagesPersistedSinceSubmission.some(
      (message) =>
        message.role === "user" &&
        message.content === activeLiveTurn.userContent,
    );
  const assistantProjectionPersisted =
    activeLiveTurn?.generationId !== null &&
    activeLiveTurn?.generationId !== undefined &&
    persistedMessages.some(
      (message) =>
        message.role === "assistant" &&
        message.generation?.publicId === activeLiveTurn.generationId,
    );
  const showLiveUser = activeLiveTurn !== null && !userProjectionPersisted;
  const showLiveAssistant =
    activeLiveTurn !== null &&
    activeLiveTurn.assistantContent.length > 0 &&
    !assistantProjectionPersisted;
  const hasRenderableMessages =
    persistedMessages.length > 0 || showLiveUser || showLiveAssistant;

  if (messages.isPending && activeLiveTurn === null) {
    return (
      <section
        className="conversation-message-history conversation-history-state"
        aria-label="Conversation messages"
      >
        <p role="status">Loading messages…</p>
      </section>
    );
  }

  if (messages.isError && activeLiveTurn === null) {
    const unavailable = conversationIsUnavailable(messages.error);

    return (
      <section
        className="conversation-message-history conversation-history-state conversation-history-error"
        aria-label="Conversation messages"
      >
        <p role="alert">
          {unavailable
            ? "Conversation unavailable."
            : "Messages are temporarily unavailable."}
        </p>
        {!unavailable ? (
          <button
            className="text-button"
            disabled={messages.isFetching}
            type="button"
            onClick={() => void messages.refetch()}
          >
            {messages.isFetching ? "Retrying…" : "Retry"}
          </button>
        ) : null}
      </section>
    );
  }

  if (!hasRenderableMessages) {
    return (
      <section
        className="conversation-message-history conversation-history-state"
        aria-label="Conversation messages"
      >
        <p>No messages yet.</p>
      </section>
    );
  }

  return (
    <section
      className="conversation-message-history"
      aria-label="Conversation messages"
    >
      {messages.isPending ? <p role="status">Loading messages…</p> : null}
      <ol className="conversation-message-list">
        {persistedMessages.map((message) => (
          <ConversationMessageItem
            key={message.publicId}
            content={message.content}
            generationStatus={message.generation?.status ?? null}
            role={message.role}
          />
        ))}
        {showLiveUser ? (
          <ConversationMessageItem
            content={activeLiveTurn.userContent}
            generationStatus={null}
            live
            role="user"
          />
        ) : null}
        {showLiveAssistant ? (
          <ConversationMessageItem
            content={activeLiveTurn.assistantContent}
            generationStatus="running"
            live
            role="assistant"
          />
        ) : null}
      </ol>
    </section>
  );
}
