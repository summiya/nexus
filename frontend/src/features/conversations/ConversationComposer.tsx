import { type FormEvent, type KeyboardEvent, useState } from "react";

import type {
  SubmissionFeedback,
  SubmissionPhase,
  SubmissionResult,
} from "./useConversationSubmission";

interface ConversationComposerProps {
  feedback: SubmissionFeedback | null;
  phase: SubmissionPhase;
  onSubmit: (content: string) => Promise<SubmissionResult>;
}

const feedbackMessages: Record<SubmissionFeedback["kind"], string> = {
  delivery_uncertain:
    "We couldn't confirm whether the message was sent. Check the conversation before trying again.",
  generation_failure: "The response could not be completed.",
  stream_interrupted:
    "The response was interrupted. Check the conversation before trying again.",
  submission_rejected: "The message was not sent. Please review it and try again.",
};

export function ConversationComposer({
  feedback,
  phase,
  onSubmit,
}: ConversationComposerProps) {
  const [draft, setDraft] = useState("");
  const active = phase !== "idle";
  const normalizedDraft = draft.trim();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active || normalizedDraft.length === 0) {
      return;
    }

    const result = await onSubmit(normalizedDraft);
    if (result === "accepted") {
      setDraft("");
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
    <form className="conversation-composer" onSubmit={handleSubmit}>
      <label htmlFor="conversation-message">Message</label>
      <div className="conversation-composer-controls">
        <textarea
          id="conversation-message"
          autoComplete="off"
          disabled={active}
          placeholder="Message Nexus"
          rows={2}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          className="primary-button conversation-send-button"
          disabled={active || normalizedDraft.length === 0}
          type="submit"
        >
          {phase === "submitting"
            ? "Sending…"
            : phase === "generating"
              ? "Generating…"
              : "Send"}
        </button>
      </div>
      {active ? (
        <p className="conversation-submission-status" role="status">
          {phase === "submitting" ? "Sending message…" : "Generating…"}
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