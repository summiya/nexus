import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureApiAuthentication } from "../../services/api/client";
import { NexusApiError } from "../../services/api/error";
import { streamConversationMessage } from "./stream";
import type {
  ConversationStreamEvent,
  StreamConversationMessageInput,
} from "./types";

const conversationId = "11111111-1111-4111-8111-111111111111";
const generationId = "22222222-2222-4222-8222-222222222222";
const assistantMessageId = "33333333-3333-4333-8333-333333333333";
const idempotencyKey = "44444444-4444-4444-8444-444444444444";

const defaultInput: StreamConversationMessageInput = {
  conversationPublicId: conversationId,
  content: "Explain SSE",
  model: "openai/gpt-5",
};

function eventFrame(event: string, data: unknown, lineEnding = "\n"): string {
  return [`event: ${event}`, `data: ${JSON.stringify(data)}`, "", ""].join(
    lineEnding,
  );
}

function startedFrame(lineEnding = "\n"): string {
  return eventFrame(
    "generation.started",
    {
      conversation_id: conversationId,
      generation_id: generationId,
      model: "openai/gpt-5",
    },
    lineEnding,
  );
}

function streamResponse(
  chunks: string[],
  contentType = "text/event-stream",
): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": contentType } },
  );
}

function errorResponse(
  code: string,
  message: string,
  status: number,
): Response {
  return new Response(
    JSON.stringify({ error: { code, message, request_id: "req_stream" } }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

async function collectEvents(
  input: StreamConversationMessageInput = defaultInput,
): Promise<ConversationStreamEvent[]> {
  const events: ConversationStreamEvent[] = [];
  for await (const event of streamConversationMessage(input)) {
    events.push(event);
  }
  return events;
}

describe("Conversation message streaming", () => {
  beforeEach(() => {
    configureApiAuthentication(undefined);
  });

  afterEach(() => {
    configureApiAuthentication(undefined);
  });

  it("starts lazily and sends the exact authenticated POST request", async () => {
    const abortController = new AbortController();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(streamResponse([startedFrame()]));
    const stream = streamConversationMessage({
      ...defaultInput,
      conversationPublicId: "conversation/id",
      idempotencyKey,
      signal: abortController.signal,
    });

    expect(fetchMock).not.toHaveBeenCalled();
    await expect(stream.next()).resolves.toMatchObject({ done: false });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/conversations/conversation%2Fid/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          content: "Explain SSE",
          model: "openai/gpt-5",
        }),
        signal: abortController.signal,
      }),
    );
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Idempotency-Key")).toBe(idempotencyKey);
    await stream.return(undefined);
  });

  it("omits the idempotency header when the caller does not supply one", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(streamResponse([startedFrame()]));

    await collectEvents();

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.has("Idempotency-Key")).toBe(false);
  });

  it("maps every supported application event to camelCase", async () => {
    const frames = [
      startedFrame(),
      eventFrame("message.delta", {
        conversation_id: conversationId,
        generation_id: generationId,
        delta: "Hello",
      }),
      eventFrame("generation.usage", {
        generation_id: generationId,
        input_tokens: 10,
        output_tokens: 4,
        total_tokens: 14,
      }),
      eventFrame("generation.completed", {
        conversation_id: conversationId,
        generation_id: generationId,
        assistant_message_id: assistantMessageId,
        finish_reason: "stop",
      }),
    ];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(streamResponse(frames));

    await expect(collectEvents()).resolves.toEqual([
      {
        type: "generation.started",
        conversationId,
        generationId,
        model: "openai/gpt-5",
      },
      {
        type: "message.delta",
        conversationId,
        generationId,
        delta: "Hello",
      },
      {
        type: "generation.usage",
        generationId,
        inputTokens: 10,
        outputTokens: 4,
        totalTokens: 14,
      },
      {
        type: "generation.completed",
        conversationId,
        generationId,
        assistantMessageId,
        finishReason: "stop",
      },
    ]);
  });

  it.each([
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "unknown",
  ] as const)("accepts the %s finish reason", async (finishReason) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        eventFrame("generation.completed", {
          conversation_id: conversationId,
          generation_id: generationId,
          assistant_message_id: assistantMessageId,
          finish_reason: finishReason,
        }),
      ]),
    );

    await expect(collectEvents()).resolves.toMatchObject([
      { type: "generation.completed", finishReason },
    ]);
  });

  it("yields generation.error as a normal typed application event", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        eventFrame("generation.error", {
          generation_id: generationId,
          kind: "incomplete_provider_stream",
          message: "The generation could not be completed.",
        }),
      ]),
    );

    await expect(collectEvents()).resolves.toEqual([
      {
        type: "generation.error",
        generationId,
        kind: "incomplete_provider_stream",
        message: "The generation could not be completed.",
      },
    ]);
  });

  it("parses an event split across arbitrary chunks", async () => {
    const frame = startedFrame();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        frame.slice(0, 7),
        frame.slice(7, 29),
        frame.slice(29, 61),
        frame.slice(61),
      ]),
    );

    await expect(collectEvents()).resolves.toMatchObject([
      { type: "generation.started", generationId },
    ]);
  });

  it("parses multiple events from one chunk", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        startedFrame() +
          eventFrame("message.delta", {
            conversation_id: conversationId,
            generation_id: generationId,
            delta: "chunk",
          }),
      ]),
    );

    await expect(collectEvents()).resolves.toMatchObject([
      { type: "generation.started" },
      { type: "message.delta", delta: "chunk" },
    ]);
  });

  it.each([
    ["LF", "\n"],
    ["CRLF", "\r\n"],
    ["CR", "\r"],
  ])("supports %s line endings", async (_name, lineEnding) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([startedFrame(lineEnding)]),
    );

    await expect(collectEvents()).resolves.toMatchObject([
      { type: "generation.started" },
    ]);
  });

  it("combines data lines and ignores comments and other SSE fields", async () => {
    const frame = [
      ": ping",
      "",
      "event: generation.started",
      `data: {"conversation_id":"${conversationId}",`,
      `data: "generation_id":"${generationId}",`,
      'data: "model":"openai/gpt-5"}',
      "id: ignored-id",
      "retry: 1000",
      "extension: ignored-value",
      "",
      "",
    ].join("\n");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(streamResponse([frame]));

    await expect(collectEvents()).resolves.toMatchObject([
      { type: "generation.started", generationId },
    ]);
  });

  it.each(["text/event-stream", "text/event-stream; charset=utf-8"])(
    "accepts the %s content type",
    async (contentType) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        streamResponse([startedFrame()], contentType),
      );

      await expect(collectEvents()).resolves.toHaveLength(1);
    },
  );

  it("rejects another successful content type and releases its body", async () => {
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(collectEvents()).rejects.toThrow(
      "The Conversation stream returned an invalid response.",
    );
    expect(cancelled).toBe(true);
  });

  it("rejects a successful response without a readable body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    await expect(collectEvents()).rejects.toThrow(
      "The Conversation stream returned an invalid response.",
    );
  });

  it("rejects malformed JSON without leaking its contents", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        "event: generation.started\ndata: secret-invalid-json\n\n",
      ]),
    );

    let thrownError: unknown;
    try {
      await collectEvents();
    } catch (error) {
      thrownError = error;
    }

    expect(thrownError).toEqual(
      new Error("The Conversation stream returned an invalid response."),
    );
    expect(String(thrownError)).not.toContain("secret-invalid-json");
  });

  it("rejects an unknown application event", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([eventFrame("generation.future", {})]),
    );

    await expect(collectEvents()).rejects.toThrow(
      "The Conversation stream returned an invalid response.",
    );
  });

  it("rejects a payload that does not match the strict event schema", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        eventFrame("generation.started", {
          conversation_id: "not-a-uuid",
          generation_id: generationId,
          model: "openai/gpt-5",
          unexpected: "do-not-trust",
        }),
      ]),
    );

    await expect(collectEvents()).rejects.toThrow(
      "The Conversation stream returned an invalid response.",
    );
  });

  it("rejects an unterminated frame at EOF", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        `event: generation.started\ndata: {"conversation_id":"${conversationId}"}`,
      ]),
    );

    await expect(collectEvents()).rejects.toThrow(
      "The Conversation stream returned an invalid response.",
    );
  });

  it("allows a clean EOF without a terminal application event", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([startedFrame()]),
    );

    await expect(collectEvents()).resolves.toMatchObject([
      { type: "generation.started" },
    ]);
  });

  it("propagates an HTTP failure before streaming as NexusApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      errorResponse("CONFLICT", "Generation already running", 409),
    );

    await expect(collectEvents()).rejects.toEqual(
      new NexusApiError(
        "Generation already running",
        409,
        "CONFLICT",
        "req_stream",
      ),
    );
  });

  it("propagates a network failure before streaming unchanged", async () => {
    const networkError = new TypeError("Failed to fetch");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(networkError);

    await expect(collectEvents()).rejects.toBe(networkError);
  });

  it("propagates an abort before a streaming response unchanged", async () => {
    const abortController = new AbortController();
    const abortError = new DOMException("Stopped", "AbortError");
    abortController.abort(abortError);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(abortError);

    await expect(
      collectEvents({ ...defaultInput, signal: abortController.signal }),
    ).rejects.toBe(abortError);
  });

  it("propagates a network failure during stream reading unchanged", async () => {
    const networkError = new TypeError("Connection lost");
    const encoder = new TextEncoder();
    let firstPull = true;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (firstPull) {
          firstPull = false;
          controller.enqueue(encoder.encode(startedFrame()));
          return;
        }
        controller.error(networkError);
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    await expect(collectEvents()).rejects.toBe(networkError);
  });

  it("refreshes an expired access token once before consuming the stream", async () => {
    let accessToken = "expired-token";
    const refreshAccessToken = vi.fn(async (expiredToken: string) => {
      expect(expiredToken).toBe("expired-token");
      accessToken = "new-token";
    });
    configureApiAuthentication({
      getAccessToken: () => accessToken,
      refreshAccessToken,
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        errorResponse("ACCESS_TOKEN_EXPIRED", "Access token has expired.", 401),
      )
      .mockResolvedValueOnce(streamResponse([startedFrame()]));

    await expect(collectEvents()).resolves.toHaveLength(1);

    expect(refreshAccessToken).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstHeaders = fetchMock.mock.calls[0][1]?.headers as Headers;
    const retryHeaders = fetchMock.mock.calls[1][1]?.headers as Headers;
    expect(firstHeaders.get("Authorization")).toBe("Bearer expired-token");
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-token");
  });

  it("propagates abort while reading without wrapping it", async () => {
    const abortController = new AbortController();
    const abortError = new DOMException("Stopped", "AbortError");
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(startedFrame()));
        abortController.signal.addEventListener("abort", () => {
          controller.error(abortController.signal.reason);
        });
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    const stream = streamConversationMessage({
      ...defaultInput,
      signal: abortController.signal,
    });

    await expect(stream.next()).resolves.toMatchObject({ done: false });
    const pending = stream.next();
    abortController.abort(abortError);

    await expect(pending).rejects.toBe(abortError);
  });

  it("cancels the response body when the consumer closes early", async () => {
    let cancelled = false;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(startedFrame()));
      },
      cancel() {
        cancelled = true;
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    const stream = streamConversationMessage(defaultInput);

    await expect(stream.next()).resolves.toMatchObject({ done: false });
    await stream.return(undefined);

    expect(cancelled).toBe(true);
  });

  it("does not let cleanup failure replace a parsing error", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode("event: generation.started\ndata: invalid\n\n"),
        );
      },
      cancel() {
        throw new Error("cleanup failed");
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    await expect(collectEvents()).rejects.toThrow(
      "The Conversation stream returned an invalid response.",
    );
  });
});
