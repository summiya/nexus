import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  ConversationComposer,
  ConversationMessageHistory,
  ConversationModelSelector,
  ConversationSidebar,
  type CreatedConversation,
  type SubmissionResult,
  useCreateConversationMutation,
  useConversationSubmission,
  useChatModelsQuery,
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
  const chatModelsQuery = useChatModelsQuery();
  const [creationFeedback, setCreationFeedback] = useState<{
    kind: "conversation_creation_failed";
  } | null>(null);
  const [composerRevision, setComposerRevision] = useState(0);
  const [explicitModelPublicId, setExplicitModelPublicId] = useState<
    string | null
  >(null);
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
    setExplicitModelPublicId(null);
    setComposerRevision((revision) => revision + 1);
    resetForConversationChange();
  }, [conversationPublicId, resetCreation, resetForConversationChange]);

  useEffect(() => {
    if (!chatModelsQuery.isSuccess || explicitModelPublicId === null) {
      return;
    }

    if (
      !chatModelsQuery.data.items.some(
        (model) => model.publicId === explicitModelPublicId,
      )
    ) {
      setExplicitModelPublicId(null);
    }
  }, [chatModelsQuery.data, chatModelsQuery.isSuccess, explicitModelPublicId]);

  async function submitMessage(content: string): Promise<SubmissionResult> {
    setCreationFeedback(null);
    const selectableModels = chatModelsQuery.data;
    const selectedExplicitModelPublicId =
      explicitModelPublicId !== null &&
      selectableModels?.items.some(
        (model) => model.publicId === explicitModelPublicId,
      ) &&
      explicitModelPublicId !== selectableModels.defaultModelPublicId
        ? explicitModelPublicId
        : null;

    if (conversationPublicId !== undefined) {
      return submit({
        conversationPublicId,
        content,
        ...(selectedExplicitModelPublicId === null
          ? {}
          : { modelPublicId: selectedExplicitModelPublicId }),
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
        refreshConversationList: true,
        ...(selectedExplicitModelPublicId === null
          ? {}
          : { modelPublicId: selectedExplicitModelPublicId }),
      });
    } finally {
      if (activeFirstMessageRef.current === operation) {
        activeFirstMessageRef.current = null;
      }
    }
  }

  const effectivePhase =
    conversationPublicId === undefined && creationPending ? "creating" : phase;
  const hasUsableExplicitSelection =
    explicitModelPublicId !== null &&
    chatModelsQuery.data?.items.some(
      (model) => model.publicId === explicitModelPublicId,
    ) === true;
  const modelSubmissionDisabled =
    !chatModelsQuery.isSuccess ||
    chatModelsQuery.data.items.length === 0 ||
    (chatModelsQuery.data.defaultModelPublicId === null &&
      !hasUsableExplicitSelection);

  const modelSelector = (
    <ConversationModelSelector
      models={chatModelsQuery.data?.items ?? []}
      defaultModelPublicId={chatModelsQuery.data?.defaultModelPublicId ?? null}
      explicitModelPublicId={explicitModelPublicId}
      isLoading={chatModelsQuery.isPending}
      isError={chatModelsQuery.isError}
      disabled={effectivePhase !== "idle"}
      onChange={setExplicitModelPublicId}
      onRetry={() => {
        void chatModelsQuery.refetch();
      }}
    />
  );

  const composer = (
    <ConversationComposer
      key={composerRevision}
      feedback={creationFeedback ?? feedback}
      phase={effectivePhase}
      submissionDisabled={modelSubmissionDisabled}
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
        <div className="conversation-input-panel">
          {modelSelector}
          {composer}
        </div>
      </>
    );
  }

  return (
    <>
      <ConversationMessageHistory
        conversationPublicId={conversationPublicId}
        liveTurn={liveTurn}
      />
      <div className="conversation-input-panel">
        {modelSelector}
        {composer}
      </div>
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
