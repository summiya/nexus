import { NexusApiError } from "../../services/api/error";
import { useConversationMessagesQuery } from "./queries";
import type {
  ConversationMessage,
  ConversationMessageRole,
  GenerationStatus,
} from "./types";

interface ConversationMessageHistoryProps {
  conversationPublicId: string;
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
  message,
}: {
  message: ConversationMessage;
}) {
  const generationStatus = message.generation
    ? generationStatusMessage(message.generation.status)
    : null;
  const generationIsActive =
    message.generation?.status === "pending" ||
    message.generation?.status === "running";

  return (
    <li className={`conversation-message conversation-message-${message.role}`}>
      <article>
        <p className="conversation-message-role">{roleLabels[message.role]}</p>
        <p className="conversation-message-content">{message.content}</p>
        {generationStatus ? (
          <p
            className={`conversation-generation-status conversation-generation-status-${message.generation?.status}`}
            role={generationIsActive ? "status" : undefined}
          >
            {generationStatus}
          </p>
        ) : null}
      </article>
    </li>
  );
}

export function ConversationMessageHistory({
  conversationPublicId,
}: ConversationMessageHistoryProps) {
  const messages = useConversationMessagesQuery(conversationPublicId);

  if (messages.isPending) {
    return (
      <section
        className="conversation-message-history conversation-history-state"
        aria-label="Conversation messages"
      >
        <p role="status">Loading messages…</p>
      </section>
    );
  }

  if (messages.isError) {
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

  if (messages.data.length === 0) {
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
      <ol className="conversation-message-list">
        {messages.data.map((message) => (
          <ConversationMessageItem key={message.publicId} message={message} />
        ))}
      </ol>
    </section>
  );
}
