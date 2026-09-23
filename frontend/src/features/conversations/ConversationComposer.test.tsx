import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConversationComposer } from "./ConversationComposer";
import type {
  SubmissionFeedback,
  SubmissionPhase,
  SubmissionResult,
} from "./useConversationSubmission";

function renderComposer({
  feedback = null,
  phase = "idle",
  result = "accepted",
}: {
  feedback?: SubmissionFeedback | null;
  phase?: SubmissionPhase;
  result?: SubmissionResult;
} = {}) {
  const onSubmit = vi.fn().mockResolvedValue(result);
  const rendered = render(
    <ConversationComposer
      feedback={feedback}
      phase={phase}
      onSubmit={onSubmit}
    />,
  );
  return { ...rendered, onSubmit };
}

describe("ConversationComposer", () => {
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

  it.each(["submitting", "generating"] satisfies SubmissionPhase[])(
    "disables duplicate submission while %s",
    (phase) => {
      const { onSubmit } = renderComposer({ phase });

      expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
      expect(screen.getByRole("button")).toBeDisabled();
      expect(screen.getByRole("status")).toBeInTheDocument();
      expect(onSubmit).not.toHaveBeenCalled();
    },
  );

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
  ] satisfies Array<[SubmissionFeedback["kind"], string]>)(
    "maps %s to fixed safe feedback",
    (kind, message) => {
      renderComposer({ feedback: { kind } });

      expect(screen.getByRole("alert")).toHaveTextContent(message);
    },
  );
});