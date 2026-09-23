import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { conversationKeys } from "./queries";
import { streamConversationMessage } from "./stream";

export type SubmissionPhase = "idle" | "submitting" | "generating";

export type SubmissionFeedback =
  | { kind: "delivery_uncertain" }
  | { kind: "generation_failure" }
  | { kind: "stream_interrupted" };

export type SubmissionResult =
  "accepted" | "uncertain" | "cancelled" | "ignored" | "not_submitted";

interface SubmitConversationMessageInput {
  conversationPublicId: string;
  content: string;
  model: string;
}

interface ActiveSubmission {
  controller: AbortController;
  conversationPublicId: string;
  operationId: number;
}

interface SubmissionState {
  phase: SubmissionPhase;
  feedback: SubmissionFeedback | null;
}

const idleState: SubmissionState = {
  phase: "idle",
  feedback: null,
};

export function useConversationSubmission() {
  const queryClient = useQueryClient();
  const activeSubmissionRef = useRef<ActiveSubmission | null>(null);
  const nextOperationIdRef = useRef(0);
  const mountedRef = useRef(true);
  const [state, setState] = useState<SubmissionState>(idleState);

  const operationIsCurrent = useCallback(
    (operation: ActiveSubmission) =>
      mountedRef.current &&
      activeSubmissionRef.current?.operationId === operation.operationId,
    [],
  );

  const resetForConversationChange = useCallback(() => {
    const activeSubmission = activeSubmissionRef.current;
    activeSubmissionRef.current = null;
    activeSubmission?.controller.abort();
    if (mountedRef.current) {
      setState(idleState);
    }
  }, []);

  const submit = useCallback(
    async ({
      conversationPublicId,
      content,
      model,
    }: SubmitConversationMessageInput): Promise<SubmissionResult> => {
      if (activeSubmissionRef.current !== null) {
        return "ignored";
      }

      const operation: ActiveSubmission = {
        controller: new AbortController(),
        conversationPublicId,
        operationId: nextOperationIdRef.current + 1,
      };
      nextOperationIdRef.current = operation.operationId;
      activeSubmissionRef.current = operation;
      setState({ phase: "submitting", feedback: null });

      let accepted = false;
      let attempted = false;
      let feedback: SubmissionFeedback | null = null;
      let result: SubmissionResult = "not_submitted";

      try {
        const idempotencyKey = crypto.randomUUID();
        attempted = true;

        for await (const event of streamConversationMessage({
          conversationPublicId,
          content,
          model,
          idempotencyKey,
          signal: operation.controller.signal,
        })) {
          accepted = true;
          if (operationIsCurrent(operation)) {
            setState({ phase: "generating", feedback: null });
          }

          if (event.type === "generation.error") {
            feedback = { kind: "generation_failure" };
          }
        }

        if (accepted) {
          result = "accepted";
        } else {
          feedback = { kind: "delivery_uncertain" };
          result = "uncertain";
        }
      } catch {
        if (operation.controller.signal.aborted) {
          result = "cancelled";
        } else if (!attempted) {
          result = "not_submitted";
        } else if (accepted) {
          feedback = { kind: "stream_interrupted" };
          result = "accepted";
        } else {
          feedback = { kind: "delivery_uncertain" };
          result = "uncertain";
        }
      } finally {
        if (attempted) {
          await queryClient.invalidateQueries({
            queryKey: conversationKeys.messages(operation.conversationPublicId),
          });
        }

        if (operationIsCurrent(operation)) {
          activeSubmissionRef.current = null;
          setState({ phase: "idle", feedback });
        }
      }

      return result;
    },
    [operationIsCurrent, queryClient],
  );

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      const activeSubmission = activeSubmissionRef.current;
      activeSubmissionRef.current = null;
      activeSubmission?.controller.abort();
    };
  }, []);

  return {
    feedback: state.feedback,
    phase: state.phase,
    resetForConversationChange,
    submit,
  };
}
