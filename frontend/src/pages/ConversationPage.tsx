import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  ConversationComposer,
  ConversationMessageHistory,
  ConversationModelSelector,
  type CreatedConversation,
  type SubmissionResult,
  useCreateConversationMutation,
  useConversationSubmission,
  useChatModelsQuery,
} from "../features/conversations";

import "../styles/nexus-chat-experience.css";

const SUGGESTED_PROMPTS = [
  {
    id: "plan",
    icon: "▦",
    title: "Plan a project",
    description: "Break an idea into milestones",
    prompt:
      "Help me plan a project with goals, milestones, and a delivery checklist.",
  },
  {
    id: "architecture",
    icon: "⌘",
    title: "Review architecture",
    description: "Think through system trade-offs",
    prompt:
      "Help me review a software architecture for scalability, reliability, and security.",
  },
  {
    id: "writing",
    icon: "✧",
    title: "Draft something",
    description: "Turn a thought into a clear draft",
    prompt: "Help me draft a concise professional project proposal.",
  },
  {
    id: "ideas",
    icon: "◇",
    title: "Explore an idea",
    description: "Go from question to direction",
    prompt:
      "Let's brainstorm three approaches to my idea and compare the trade-offs.",
  },
] as const;

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
  const {
    feedback,
    liveTurn,
    phase,
    resetForConversationChange,
    stop,
    submit,
  } = useConversationSubmission();
  const chatModelsQuery = useChatModelsQuery();
  const [creationFeedback, setCreationFeedback] = useState<{
    kind: "conversation_creation_failed";
  } | null>(null);
  const [composerRevision, setComposerRevision] = useState(0);
  const [suggestedPrompt, setSuggestedPrompt] = useState<{
    revision: number;
    text: string;
  } | null>(null);
  const nextSuggestionRevision = useRef(0);
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
    setSuggestedPrompt(null);
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
      modelSelector={modelSelector}
      suggestedPrompt={suggestedPrompt}
      phase={effectivePhase}
      submissionDisabled={modelSubmissionDisabled}
      onStop={stop}
      onSubmit={submitMessage}
    />
  );

  const workspaceHeader = (
    <header className="conversation-workspace-topline">
      <span className="conversation-workspace-location">
        <span aria-hidden="true">✧</span> NEXUS
        <span aria-hidden="true" className="conversation-breadcrumb-separator">
          /
        </span>
        {conversationPublicId === undefined
          ? "New conversation"
          : "Conversation"}
      </span>
      <span className="conversation-workspace-private">
        <span aria-hidden="true">◇</span> Organization workspace
      </span>
    </header>
  );

  if (conversationPublicId === undefined) {
    return (
      <>
        {workspaceHeader}
        <div className="conversation-workspace-placeholder">
          <div className="conversation-welcome-mark" aria-hidden="true">
            ✧
          </div>
          <p className="eyebrow">YOUR INTELLIGENT WORKSPACE</p>
          <h2>Start a new conversation</h2>
          <p>
            Think, create and explore with your organization's configured
            models. Everything starts with a great question.
          </p>
          <div
            className="conversation-suggestion-grid"
            aria-label="Suggested prompts"
          >
            {SUGGESTED_PROMPTS.map((suggestion) => (
              <button
                key={suggestion.id}
                type="button"
                className="conversation-suggestion-card"
                onClick={() => {
                  const revision = nextSuggestionRevision.current + 1;
                  nextSuggestionRevision.current = revision;
                  setSuggestedPrompt({ revision, text: suggestion.prompt });
                }}
              >
                <span
                  className="conversation-suggestion-icon"
                  aria-hidden="true"
                >
                  {suggestion.icon}
                </span>
                <span className="conversation-suggestion-text">
                  <strong>{suggestion.title}</strong>
                  <small>{suggestion.description}</small>
                </span>
                <span
                  className="conversation-suggestion-arrow"
                  aria-hidden="true"
                >
                  ↗
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="conversation-input-panel">{composer}</div>
      </>
    );
  }

  return (
    <>
      {workspaceHeader}
      <ConversationMessageHistory
        conversationPublicId={conversationPublicId}
        liveTurn={liveTurn}
      />
      <div className="conversation-input-panel">{composer}</div>
    </>
  );
}

export function ConversationPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();

  return (
    <section className="conversation-shell">
      <section
        className="conversation-workspace"
        aria-label="Conversation workspace"
      >
        <ConversationWorkspace conversationPublicId={conversationId} />
      </section>
    </section>
  );
}
