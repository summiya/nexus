import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ConversationComposer,
  type ConversationComposerFeedback,
  type ConversationComposerPhase,
} from "./ConversationComposer";
import type { SubmissionResult } from "./useConversationSubmission";

function renderComposer({
  feedback = null,
  phase = "idle",
  result = "accepted",
  submissionDisabled = false,
}: {
  feedback?: ConversationComposerFeedback | null;
  phase?: ConversationComposerPhase;
  result?: SubmissionResult;
  submissionDisabled?: boolean;
} = {}) {
  const onStop = vi.fn();
  const onSubmit = vi.fn().mockResolvedValue(result);
  const rendered = render(
    <ConversationComposer
      feedback={feedback}
      phase={phase}
      submissionDisabled={submissionDisabled}
      onStop={onStop}
      onSubmit={onSubmit}
    />,
  );
  return { ...rendered, onStop, onSubmit };
}

describe("ConversationComposer", () => {
  it("exposes dedicated layout hooks for the message input and send action", () => {
    renderComposer();

    const textarea = screen.getByRole("textbox", { name: "Message" });
    const sendButton = screen.getByRole("button", { name: "Send" });

    expect(textarea).toHaveClass("conversation-message-input");
    expect(textarea.parentElement).toHaveClass(
      "conversation-composer-controls",
    );
    expect(sendButton).toHaveClass("conversation-send-button");
  });

  it("stores the draft locally and submits trimmed content", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Message" });

    await user.type(textarea, "  Explain event streams  ");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith("Explain event streams");
    expect(textarea).toHaveValue("");
  });

  it.each(["", "   \n  "])("blocks a blank draft %j", async (draft) => {
    const user = userEvent.setup();
    const { onSubmit } = renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Message" });

    if (draft) {
      await user.type(textarea, draft);
    }

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits with Enter", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderComposer();

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "Send with Enter{Enter}",
    );

    expect(onSubmit).toHaveBeenCalledWith("Send with Enter");
  });

  it("uses Shift+Enter for a newline", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Message" });

    await user.type(textarea, "First line");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(textarea, "Second line");

    expect(textarea).toHaveValue("First line\nSecond line");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not submit Enter during IME composition", () => {
    const { onSubmit } = renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Message" });

    fireEvent.change(textarea, { target: { value: " composing " } });
    fireEvent.keyDown(textarea, { key: "Enter", isComposing: true });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea).toHaveValue(" composing ");
  });

  it("disables submission while creating a Conversation", () => {
    const { onSubmit } = renderComposer({ phase: "creating" });

    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Creating conversation…",
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it.each(["submitting", "generating"] satisfies ConversationComposerPhase[])(
    "shows an enabled Stop action and generating placeholder while %s",
    async (phase) => {
      const user = userEvent.setup();
      const { onStop, onSubmit } = renderComposer({ phase });
      const textarea = screen.getByRole("textbox", { name: "Message" });

      expect(textarea).toBeDisabled();
      expect(textarea).toHaveAttribute("placeholder", "Generating message…");
      expect(screen.queryByRole("status")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Stop" }));

      expect(onStop).toHaveBeenCalledOnce();
      expect(onSubmit).not.toHaveBeenCalled();
    },
  );

  it("blocks model-dependent submission while preserving an editable draft", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderComposer({ submissionDisabled: true });
    const textarea = screen.getByRole("textbox", { name: "Message" });

    await user.type(textarea, "Draft while models load");
    expect(textarea).toHaveValue("Draft while models load");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps the composer clear after a user-stopped generation", async () => {
    const user = userEvent.setup();
    renderComposer({ result: "stopped" });
    const textarea = screen.getByRole("textbox", { name: "Message" });

    await user.type(textarea, "Stop this response");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(textarea).toHaveValue("");
  });

  it.each(["uncertain", "not_submitted"] satisfies SubmissionResult[])(
    "retains the draft when submission result is %s",
    async (result) => {
      const user = userEvent.setup();
      renderComposer({ result });
      const textarea = screen.getByRole("textbox", { name: "Message" });

      await user.type(textarea, "Keep this draft");
      await user.click(screen.getByRole("button", { name: "Send" }));

      expect(textarea).toHaveValue("Keep this draft");
    },
  );

  it.each([
    [
      "conversation_creation_failed",
      "We couldn't confirm the conversation was created. Check your conversations before trying again.",
    ],
    [
      "delivery_uncertain",
      "We couldn't confirm whether the message was sent. Check the conversation before trying again.",
    ],
    ["generation_failure", "The response could not be completed."],
    [
      "stream_interrupted",
      "The response was interrupted. Check the conversation before trying again.",
    ],
    [
      "submission_rejected",
      "The message was not sent. Please review it and try again.",
    ],
  ] satisfies Array<[ConversationComposerFeedback["kind"], string]>)(
    "maps %s to fixed safe feedback",
    (kind, message) => {
      renderComposer({ feedback: { kind } });

      expect(screen.getByRole("alert")).toHaveTextContent(message);
    },
  );
});
