import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { env } from "../config/env";
import {
  ConversationComposer,
  ConversationMessageHistory,
  ConversationSidebar,
  type CreatedConversation,
  type SubmissionResult,
  useCreateConversationMutation,
  useConversationSubmission,
} from "../features/conversations";

interface FirstMessageOperation {
  id: number;
}

function ConversationWorkspace({
  conversationPublicId,
}: {
  conversationPublicId: string | undefined;
}) {
  const navigate = useNavigate();
  const {
    isPending: creationPending,
    mutateAsync: createConversation,
    reset: resetCreation,
  } = useCreateConversationMutation();
  const { feedback, liveTurn, phase, resetForConversationChange, submit } =
    useConversationSubmission();
  const [creationFeedback, setCreationFeedback] = useState<{
    kind: "conversation_creation_failed";
  } | null>(null);
  const [composerRevision, setComposerRevision] = useState(0);
  const activeFirstMessageRef = useRef<FirstMessageOperation | null>(null);
  const expectedConversationPublicIdRef = useRef<string | null>(null);
  const nextFirstMessageOperationIdRef = useRef(0);
  const previousConversationPublicId = useRef(conversationPublicId);

  useEffect(
    () => () => {
      activeFirstMessageRef.current = null;
      expectedConversationPublicIdRef.current = null;
    },
    [],
  );

  useEffect(() => {
    if (previousConversationPublicId.current === conversationPublicId) {
      return;
    }

    previousConversationPublicId.current = conversationPublicId;

    if (expectedConversationPublicIdRef.current === conversationPublicId) {
      expectedConversationPublicIdRef.current = null;
      return;
    }

    activeFirstMessageRef.current = null;
    expectedConversationPublicIdRef.current = null;
    resetCreation();
    setCreationFeedback(null);
    setComposerRevision((revision) => revision + 1);
    resetForConversationChange();
  }, [conversationPublicId, resetCreation, resetForConversationChange]);

  async function submitMessage(content: string): Promise<SubmissionResult> {
    setCreationFeedback(null);

    if (conversationPublicId !== undefined) {
      return submit({
        conversationPublicId,
        content,
        model: env.conversationModel,
      });
    }

    if (activeFirstMessageRef.current !== null) {
      return "ignored";
    }

    const operation = {
      id: nextFirstMessageOperationIdRef.current + 1,
    };
    nextFirstMessageOperationIdRef.current = operation.id;
    activeFirstMessageRef.current = operation;
    resetCreation();

    try {
      let createdConversation: CreatedConversation;

      try {
        createdConversation = await createConversation(undefined);
      } catch {
        if (activeFirstMessageRef.current !== operation) {
          return "cancelled";
        }

        setCreationFeedback({ kind: "conversation_creation_failed" });
        return "not_submitted";
      }

      if (activeFirstMessageRef.current !== operation) {
        return "cancelled";
      }

      expectedConversationPublicIdRef.current = createdConversation.publicId;
      navigate(
        `/conversations/${encodeURIComponent(createdConversation.publicId)}`,
      );

      return await submit({
        conversationPublicId: createdConversation.publicId,
        content,
        model: env.conversationModel,
      });
    } finally {
      if (activeFirstMessageRef.current === operation) {
        activeFirstMessageRef.current = null;
      }
    }
  }

  const composer = (
    <ConversationComposer
      key={composerRevision}
      feedback={creationFeedback ?? feedback}
      phase={
        conversationPublicId === undefined && creationPending
          ? "creating"
          : phase
      }
      onSubmit={submitMessage}
    />
  );

  if (conversationPublicId === undefined) {
    return (
      <>
        <div className="conversation-workspace-placeholder">
          <p className="eyebrow">NEXUS</p>
          <h2>Start a new conversation</h2>
          <p>Choose a conversation from the sidebar or begin a new chat.</p>
        </div>
        {composer}
      </>
    );
  }

  return (
    <>
      <ConversationMessageHistory
        conversationPublicId={conversationPublicId}
        liveTurn={liveTurn}
      />
      {composer}
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
