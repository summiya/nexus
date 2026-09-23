import { useParams } from "react-router-dom";

import { ConversationSidebar } from "../features/conversations";

export function ConversationPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const hasSelectedConversation = conversationId !== undefined;

  return (
    <section className="conversation-shell">
      <ConversationSidebar />

      <section
        className="conversation-workspace"
        aria-labelledby="conversation-workspace-title"
      >
        <p className="eyebrow">NEXUS</p>
        <h2 id="conversation-workspace-title">
          {hasSelectedConversation
            ? "Conversation selected"
            : "Start a new conversation"}
        </h2>
        <p>
          {hasSelectedConversation
            ? "Messages for this conversation will appear here in the next phase."
            : "Choose a conversation from the sidebar or begin a new chat."}
        </p>
      </section>
    </section>
  );
}
