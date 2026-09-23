import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationStreamEvent } from "./types";

const streamMocks = vi.hoisted(() => ({
  streamConversationMessage: vi.fn(),
}));

vi.mock("./stream", () => streamMocks);

import {
  type SubmissionResult,
  useConversationSubmission,
} from "./useConversationSubmission";

const firstConversationId = "11111111-1111-4111-8111-111111111111";
const secondConversationId = "22222222-2222-4222-8222-222222222222";
const generationId = "33333333-3333-4333-8333-333333333333";
const assistantMessageId = "44444444-4444-4444-8444-444444444444";
const idempotencyKey = "55555555-5555-4555-8555-555555555555";

const startedEvent: ConversationStreamEvent = {
  type: "generation.started",
  conversationId: firstConversationId,
  generationId,
  model: "gpt-4o-mini",
};

const completedEvent: ConversationStreamEvent = {
  type: "generation.completed",
  conversationId: firstConversationId,
  generationId,
  assistantMessageId,
  finishReason: "stop",
};

const defaultInput = {
  conversationPublicId: firstConversationId,
  content: "Explain streaming",
  model: "gpt-4o-mini",
};

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function wrapper(queryClient: QueryClient) {
  return function TestQueryClientProvider({
    children,
  }: {
    children: ReactNode;
  }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

function eventStream(
  events: ConversationStreamEvent[],
): AsyncGenerator<ConversationStreamEvent> {
  return (async function* generateEvents() {
    for (const event of events) {
      yield event;
    }
  })();
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function renderSubmissionHook(queryClient = createTestQueryClient()) {
  const rendered = renderHook(() => useConversationSubmission(), {
    wrapper: wrapper(queryClient),
  });
  return { ...rendered, queryClient };
}

describe("useConversationSubmission", () => {
  beforeEach(() => {
    streamMocks.streamConversationMessage.mockReset();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(idempotencyKey);
  });

  it("uses the target, model, one idempotency key, and one AbortSignal", async () => {
    let consumed = false;
    streamMocks.streamConversationMessage.mockImplementation(() =>
      (async function* generateEvents() {
        yield startedEvent;
        yield {
          type: "message.delta",
          conversationId: firstConversationId,
          generationId,
          delta: "ignored",
        } satisfies ConversationStreamEvent;
        yield {
          type: "generation.usage",
          generationId,
          inputTokens: 3,
          outputTokens: 2,
          totalTokens: 5,
        } satisfies ConversationStreamEvent;
        yield completedEvent;
        consumed = true;
      })(),
    );
    const queryClient = createTestQueryClient();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const refetchQueries = vi.spyOn(queryClient, "refetchQueries");
    const { result } = renderSubmissionHook(queryClient);

    let outcome: SubmissionResult | undefined;
    await act(async () => {
      outcome = await result.current.submit(defaultInput);
    });

    expect(outcome).toBe("accepted");
    expect(consumed).toBe(true);
    expect(globalThis.crypto.randomUUID).toHaveBeenCalledOnce();
    expect(streamMocks.streamConversationMessage).toHaveBeenCalledOnce();
    expect(streamMocks.streamConversationMessage).toHaveBeenCalledWith({
      ...defaultInput,
      idempotencyKey,
      signal: expect.any(AbortSignal),
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["conversations", "messages", firstConversationId],
    });
    expect(refetchQueries).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({
      phase: "idle",
      feedback: null,
    });
  });

  it("moves to generating after the first valid event", async () => {
    const releaseStream = deferred();
    streamMocks.streamConversationMessage.mockImplementation(() =>
      (async function* generateEvents() {
        yield startedEvent;
        await releaseStream.promise;
        yield completedEvent;
      })(),
    );
    const { result } = renderSubmissionHook();

    let submission!: Promise<SubmissionResult>;
    act(() => {
      submission = result.current.submit(defaultInput);
    });

    await waitFor(() => expect(result.current.phase).toBe("generating"));

    releaseStream.resolve();
    await act(async () => {
      await submission;
    });
    expect(result.current.phase).toBe("idle");
  });

  it("uses fixed generation failure feedback and ignores event details", async () => {
    streamMocks.streamConversationMessage.mockReturnValue(
      eventStream([
        startedEvent,
        {
          type: "generation.error",
          generationId,
          kind: "private_provider_failure",
          message: "sensitive provider detail",
        },
      ]),
    );
    const { result } = renderSubmissionHook();

    await act(async () => {
      expect(await result.current.submit(defaultInput)).toBe("accepted");
    });

    expect(result.current.feedback).toEqual({ kind: "generation_failure" });
    expect(JSON.stringify(result.current.feedback)).not.toContain("private");
    expect(JSON.stringify(result.current.feedback)).not.toContain("sensitive");
  });

  it("accepts clean EOF after a valid event without fabricating feedback", async () => {
    streamMocks.streamConversationMessage.mockReturnValue(
      eventStream([startedEvent]),
    );
    const { result } = renderSubmissionHook();

    await act(async () => {
      expect(await result.current.submit(defaultInput)).toBe("accepted");
    });

    expect(result.current.feedback).toBeNull();
  });

  it("treats clean EOF before any valid event as uncertain", async () => {
    streamMocks.streamConversationMessage.mockReturnValue(eventStream([]));
    const { result } = renderSubmissionHook();

    await act(async () => {
      expect(await result.current.submit(defaultInput)).toBe("uncertain");
    });

    expect(result.current.feedback).toEqual({ kind: "delivery_uncertain" });
  });

  it("treats failure before the first event as uncertain without retrying", async () => {
    streamMocks.streamConversationMessage.mockImplementation(() =>
      (async function* failBeforeEvent() {
        await Promise.reject(new Error("private transport detail"));
        yield startedEvent;
      })(),
    );
    const queryClient = createTestQueryClient();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderSubmissionHook(queryClient);

    await act(async () => {
      expect(await result.current.submit(defaultInput)).toBe("uncertain");
    });

    expect(streamMocks.streamConversationMessage).toHaveBeenCalledOnce();
    expect(result.current.feedback).toEqual({ kind: "delivery_uncertain" });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["conversations", "messages", firstConversationId],
    });
  });

  it("treats failure after acceptance as an interrupted stream", async () => {
    streamMocks.streamConversationMessage.mockImplementation(() =>
      (async function* failAfterEvent() {
        yield startedEvent;
        throw new Error("private parser detail");
      })(),
    );
    const { result } = renderSubmissionHook();

    await act(async () => {
      expect(await result.current.submit(defaultInput)).toBe("accepted");
    });

    expect(result.current.feedback).toEqual({ kind: "stream_interrupted" });
  });

  it("guards a same-tick duplicate before React rerenders", async () => {
    const releaseStream = deferred();
    streamMocks.streamConversationMessage.mockImplementation(() =>
      (async function* generateEvents() {
        await releaseStream.promise;
        yield startedEvent;
      })(),
    );
    const { result } = renderSubmissionHook();

    let firstSubmission!: Promise<SubmissionResult>;
    let duplicateSubmission!: Promise<SubmissionResult>;
    act(() => {
      firstSubmission = result.current.submit(defaultInput);
      duplicateSubmission = result.current.submit(defaultInput);
    });

    await expect(duplicateSubmission).resolves.toBe("ignored");
    expect(streamMocks.streamConversationMessage).toHaveBeenCalledOnce();
    expect(globalThis.crypto.randomUUID).toHaveBeenCalledOnce();

    releaseStream.resolve();
    await act(async () => {
      await firstSubmission;
    });
  });

  it("does not reconcile history when local setup prevents an endpoint attempt", async () => {
    vi.mocked(globalThis.crypto.randomUUID).mockImplementation(() => {
      throw new Error("UUID unavailable");
    });
    const queryClient = createTestQueryClient();
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderSubmissionHook(queryClient);

    await act(async () => {
      expect(await result.current.submit(defaultInput)).toBe("not_submitted");
    });

    expect(streamMocks.streamConversationMessage).not.toHaveBeenCalled();
    expect(invalidateQueries).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ phase: "idle", feedback: null });
  });

  it("aborts and silently resets the active operation for a Conversation change", async () => {
    let suppliedSignal: AbortSignal | undefined;
    streamMocks.streamConversationMessage.mockImplementation(
      ({ signal }: { signal?: AbortSignal }) => {
        suppliedSignal = signal;
        return (async function* waitForAbort() {
          yield startedEvent;
          await new Promise<void>((_resolve, reject) => {
            signal?.addEventListener("abort", () =>
              reject(new Error("intentional abort")),
            );
          });
        })();
      },
    );
    const queryClient = createTestQueryClient();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderSubmissionHook(queryClient);

    let submission!: Promise<SubmissionResult>;
    act(() => {
      submission = result.current.submit(defaultInput);
    });
    await waitFor(() => expect(result.current.phase).toBe("generating"));

    act(() => result.current.resetForConversationChange());

    expect(suppliedSignal?.aborted).toBe(true);
    expect(result.current).toMatchObject({ phase: "idle", feedback: null });
    await expect(submission).resolves.toBe("cancelled");
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["conversations", "messages", firstConversationId],
    });
  });

  it("prevents late A cleanup from changing B and keeps invalidation targeted", async () => {
    const releaseFirst = deferred();
    const releaseSecond = deferred();
    streamMocks.streamConversationMessage.mockImplementation(
      ({ conversationPublicId }: { conversationPublicId: string }) =>
        (async function* generateEvents() {
          yield {
            ...startedEvent,
            conversationId: conversationPublicId,
          };
          if (conversationPublicId === firstConversationId) {
            await releaseFirst.promise;
            throw new Error("late A failure");
          }
          await releaseSecond.promise;
          yield {
            ...completedEvent,
            conversationId: conversationPublicId,
          };
        })(),
    );
    const queryClient = createTestQueryClient();
    const invalidateQueries = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderSubmissionHook(queryClient);

    let firstSubmission!: Promise<SubmissionResult>;
    act(() => {
      firstSubmission = result.current.submit(defaultInput);
    });
    await waitFor(() => expect(result.current.phase).toBe("generating"));
    act(() => result.current.resetForConversationChange());

    let secondSubmission!: Promise<SubmissionResult>;
    act(() => {
      secondSubmission = result.current.submit({
        ...defaultInput,
        conversationPublicId: secondConversationId,
      });
    });
    await waitFor(() => expect(result.current.phase).toBe("generating"));

    releaseFirst.resolve();
    await act(async () => {
      await firstSubmission;
    });
    expect(result.current).toMatchObject({
      phase: "generating",
      feedback: null,
    });

    releaseSecond.resolve();
    await act(async () => {
      await secondSubmission;
    });
    expect(result.current).toMatchObject({ phase: "idle", feedback: null });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["conversations", "messages", firstConversationId],
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["conversations", "messages", secondConversationId],
    });
  });

  it("aborts the active operation when the workspace owner unmounts", async () => {
    let suppliedSignal: AbortSignal | undefined;
    streamMocks.streamConversationMessage.mockImplementation(
      ({ signal }: { signal?: AbortSignal }) => {
        suppliedSignal = signal;
        return (async function* waitForAbort() {
          yield startedEvent;
          await new Promise<void>((_resolve, reject) => {
            signal?.addEventListener("abort", () => reject(new Error("abort")));
          });
        })();
      },
    );
    const { result, unmount } = renderSubmissionHook();

    let submission!: Promise<SubmissionResult>;
    act(() => {
      submission = result.current.submit(defaultInput);
    });
    await waitFor(() => expect(result.current.phase).toBe("generating"));

    unmount();

    expect(suppliedSignal?.aborted).toBe(true);
    await expect(submission).resolves.toBe("cancelled");
  });
});
