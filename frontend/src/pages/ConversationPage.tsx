import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";

import { env } from "../config/env";
import {
  ConversationComposer,
  ConversationMessageHistory,
  ConversationSidebar,
  useConversationSubmission,
} from "../features/conversations";

function ConversationWorkspace({
  conversationPublicId,
}: {
  conversationPublicId: string | undefined;
}) {
  const { feedback, phase, resetForConversationChange, submit } =
    useConversationSubmission();
  const previousConversationPublicId = useRef(conversationPublicId);

  useEffect(() => {
    if (previousConversationPublicId.current === conversationPublicId) {
      return;
    }

    previousConversationPublicId.current = conversationPublicId;
    resetForConversationChange();
  }, [conversationPublicId, resetForConversationChange]);

  if (conversationPublicId === undefined) {
    return (
      <div className="conversation-workspace-placeholder">
        <p className="eyebrow">NEXUS</p>
        <h2>Start a new conversation</h2>
        <p>Choose a conversation from the sidebar or begin a new chat.</p>
      </div>
    );
  }

  return (
    <>
      <ConversationMessageHistory conversationPublicId={conversationPublicId} />
      <ConversationComposer
        key={conversationPublicId}
        feedback={feedback}
        phase={phase}
        onSubmit={(content) =>
          submit({
            conversationPublicId,
            content,
            model: env.conversationModel,
          })
        }
      />
    </>
  );
}

export function ConversationPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();

  return (
    <section className="conversation-shell">
      <ConversationSidebar />

      <section
        className="conversation-workspace"
        aria-label="Conversation workspace"
      >
        <ConversationWorkspace conversationPublicId={conversationId} />
      </section>
    </section>
  );
}
