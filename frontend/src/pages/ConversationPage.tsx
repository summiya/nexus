import { useParams } from "react-router-dom";

import {
  ConversationMessageHistory,
  ConversationSidebar,
} from "../features/conversations";

export function ConversationPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const hasSelectedConversation = conversationId !== undefined;

  return (
    <section className="conversation-shell">
      <ConversationSidebar />

      <section
        className="conversation-workspace"
        aria-label="Conversation workspace"
      >
        {hasSelectedConversation ? (
          <ConversationMessageHistory conversationPublicId={conversationId} />
        ) : (
          <div className="conversation-workspace-placeholder">
            <p className="eyebrow">NEXUS</p>
            <h2>Start a new conversation</h2>
            <p>Choose a conversation from the sidebar or begin a new chat.</p>
          </div>
        )}
      </section>
    </section>
  );
}
