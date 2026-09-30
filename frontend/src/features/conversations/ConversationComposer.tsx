import { type FormEvent, type KeyboardEvent, useState } from "react";

import type {
  SubmissionFeedback,
  SubmissionPhase,
  SubmissionResult,
} from "./useConversationSubmission";

export type ConversationComposerPhase = SubmissionPhase | "creating";

export type ConversationComposerFeedback =
  SubmissionFeedback | { kind: "conversation_creation_failed" };

interface ConversationComposerProps {
  feedback: ConversationComposerFeedback | null;
  phase: ConversationComposerPhase;
  onStop?: () => void;
  onSubmit: (content: string) => Promise<SubmissionResult>;
  submissionDisabled?: boolean;
}

const feedbackMessages: Record<ConversationComposerFeedback["kind"], string> = {
  conversation_creation_failed:
    "We couldn't confirm the conversation was created. Check your conversations before trying again.",
  delivery_uncertain:
    "We couldn't confirm whether the message was sent. Check the conversation before trying again.",
  generation_failure: "The response could not be completed.",
  stream_interrupted:
    "The response was interrupted. Check the conversation before trying again.",
  submission_rejected:
    "The message was not sent. Please review it and try again.",
};

export function ConversationComposer({
  feedback,
  phase,
  onStop,
  onSubmit,
  submissionDisabled = false,
}: ConversationComposerProps) {
  const [draft, setDraft] = useState("");
  const active = phase !== "idle";
  const stoppable = phase === "submitting" || phase === "generating";
  const normalizedDraft = draft.trim();
  const placeholder = stoppable ? "Generating message…" : "Message Nexus";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active || submissionDisabled || normalizedDraft.length === 0) {
      return;
    }

    const submittedDraft = normalizedDraft;
    setDraft("");

    const result = await onSubmit(submittedDraft);
    if (
      result === "uncertain" ||
      result === "not_submitted" ||
      result === "ignored"
    ) {
      setDraft(submittedDraft);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return;
    }

    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <form
      aria-busy={active}
      className="conversation-composer"
      onSubmit={handleSubmit}
    >
      <label htmlFor="conversation-message">Message</label>
      <div className="conversation-composer-controls">
        <textarea
          className="conversation-message-input"
          id="conversation-message"
          autoComplete="off"
          disabled={active}
          placeholder={placeholder}
          rows={2}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        {stoppable ? (
          <button
            className="primary-button conversation-send-button"
            disabled={onStop === undefined}
            type="button"
            onClick={onStop}
          >
            Stop
          </button>
        ) : (
          <button
            className="primary-button conversation-send-button"
            disabled={
              phase === "creating" ||
              submissionDisabled ||
              normalizedDraft.length === 0
            }
            type="submit"
          >
            {phase === "creating" ? "Creating…" : "Send"}
          </button>
        )}
      </div>
      {phase === "creating" ? (
        <p className="conversation-submission-status" role="status">
          Creating conversation…
        </p>
      ) : null}
      {feedback ? (
        <p className="conversation-submission-feedback" role="alert">
          {feedbackMessages[feedback.kind]}
        </p>
      ) : null}
    </form>
  );
}
