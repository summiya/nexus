import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { NexusApiError } from "../../services/api/error";
import { conversationKeys } from "./queries";
import { streamConversationMessage } from "./stream";
import type { ConversationMessage, ConversationStreamEvent } from "./types";

export type SubmissionPhase = "idle" | "submitting" | "generating";

export type SubmissionFeedback =
  | { kind: "delivery_uncertain" }
  | { kind: "generation_failure" }
  | { kind: "stream_interrupted" }
  | { kind: "submission_rejected" };

export type SubmissionResult =
  "accepted" | "uncertain" | "cancelled" | "ignored" | "not_submitted";

export interface LiveConversationTurn {
  projectionId: number;
  conversationPublicId: string;
  userContent: string;
  assistantContent: string;
  generationId: string | null;
  persistedMessagePublicIds: readonly string[];
}

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
  liveTurn: LiveConversationTurn | null;
}

const idleState: SubmissionState = {
  phase: "idle",
  feedback: null,
  liveTurn: null,
};

const prePersistenceRejectionStatuses = new Set([401, 403, 404, 422]);

function isKnownPrePersistenceRejection(error: unknown): boolean {
  return (
    error instanceof NexusApiError &&
    prePersistenceRejectionStatuses.has(error.status)
  );
}

function applyStreamEvent(
  state: SubmissionState,
  operation: ActiveSubmission,
  event: ConversationStreamEvent,
): SubmissionState {
  const liveTurn = state.liveTurn;
  if (liveTurn?.projectionId !== operation.operationId) {
    return state;
  }

  if (
    event.type === "generation.started" &&
    event.conversationId === operation.conversationPublicId
  ) {
    return {
      ...state,
      phase: "generating",
      liveTurn: { ...liveTurn, generationId: event.generationId },
    };
  }

  if (
    event.type === "message.delta" &&
    event.conversationId === operation.conversationPublicId &&
    (liveTurn.generationId === null ||
      liveTurn.generationId === event.generationId)
  ) {
    return {
      ...state,
      phase: "generating",
      liveTurn: {
        ...liveTurn,
        assistantContent: liveTurn.assistantContent + event.delta,
        generationId: liveTurn.generationId ?? event.generationId,
      },
    };
  }

  return { ...state, phase: "generating" };
}

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
      setState({ phase: "submitting", feedback: null, liveTurn: null });

      let accepted = false;
      let attempted = false;
      let feedback: SubmissionFeedback | null = null;
      let rejectedBeforePersistence = false;
      let result: SubmissionResult = "not_submitted";

      try {
        const idempotencyKey = crypto.randomUUID();
        attempted = true;
        const persistedMessages =
          queryClient.getQueryData<ConversationMessage[]>(
            conversationKeys.messages(conversationPublicId),
          ) ?? [];

        if (operationIsCurrent(operation)) {
          setState({
            phase: "submitting",
            feedback: null,
            liveTurn: {
              projectionId: operation.operationId,
              conversationPublicId,
              userContent: content,
              assistantContent: "",
              generationId: null,
              persistedMessagePublicIds: persistedMessages.map(
                (message) => message.publicId,
              ),
            },
          });
        }

        for await (const event of streamConversationMessage({
          conversationPublicId,
          content,
          model,
          idempotencyKey,
          signal: operation.controller.signal,
        })) {
          accepted = true;
          if (operationIsCurrent(operation)) {
            setState((currentState) =>
              applyStreamEvent(currentState, operation, event),
            );
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
      } catch (error) {
        if (operation.controller.signal.aborted) {
          result = "cancelled";
        } else if (!attempted) {
          result = "not_submitted";
        } else if (accepted) {
          feedback = { kind: "stream_interrupted" };
          result = "accepted";
        } else if (isKnownPrePersistenceRejection(error)) {
          rejectedBeforePersistence = true;
          feedback = { kind: "submission_rejected" };
          result = "not_submitted";
        } else {
          feedback = { kind: "delivery_uncertain" };
          result = "uncertain";
        }
      } finally {
        if (attempted && !rejectedBeforePersistence) {
          await queryClient.invalidateQueries({
            queryKey: conversationKeys.messages(operation.conversationPublicId),
          });
        }

        if (operationIsCurrent(operation)) {
          activeSubmissionRef.current = null;
          setState({ phase: "idle", feedback, liveTurn: null });
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
    liveTurn: state.liveTurn,
    phase: state.phase,
    resetForConversationChange,
    submit,
  };
}
