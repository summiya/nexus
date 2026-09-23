import { z } from "zod";

import { apiResponse } from "../../services/api/client";
import {
  generationFinishReasons,
  type ConversationStreamEvent,
  type GenerationCompletedEvent,
  type GenerationErrorEvent,
  type GenerationStartedEvent,
  type GenerationUsageEvent,
  type MessageDeltaEvent,
  type StreamConversationMessageInput,
} from "./types";

const uuidSchema = z.string().uuid();

const generationStartedSchema = z
  .object({
    conversation_id: uuidSchema,
    generation_id: uuidSchema,
    model: z.string(),
  })
  .strict();

const messageDeltaSchema = z
  .object({
    conversation_id: uuidSchema,
    generation_id: uuidSchema,
    delta: z.string(),
  })
  .strict();

const generationUsageSchema = z
  .object({
    generation_id: uuidSchema,
    input_tokens: z.number().int().nonnegative(),
    output_tokens: z.number().int().nonnegative(),
    total_tokens: z.number().int().nonnegative(),
  })
  .strict();

const generationCompletedSchema = z
  .object({
    conversation_id: uuidSchema,
    generation_id: uuidSchema,
    assistant_message_id: uuidSchema,
    finish_reason: z.enum(generationFinishReasons),
  })
  .strict();

const generationErrorSchema = z
  .object({
    generation_id: uuidSchema,
    kind: z.string(),
    message: z.string(),
  })
  .strict();

interface RawServerSentEvent {
  event: string;
  data: string;
}

interface ParsedLine {
  line: string;
  remainder: string;
}

function invalidStreamResponse(): Error {
  return new Error("The Conversation stream returned an invalid response.");
}

function parsePayload<T>(schema: z.ZodType<T>, data: string): T {
  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    throw invalidStreamResponse();
  }

  const result = schema.safeParse(payload);
  if (!result.success) {
    throw invalidStreamResponse();
  }
  return result.data;
}

function toConversationEvent({
  event,
  data,
}: RawServerSentEvent): ConversationStreamEvent {
  switch (event) {
    case "generation.started": {
      const payload = parsePayload(generationStartedSchema, data);
      return {
        type: event,
        conversationId: payload.conversation_id,
        generationId: payload.generation_id,
        model: payload.model,
      } satisfies GenerationStartedEvent;
    }
    case "message.delta": {
      const payload = parsePayload(messageDeltaSchema, data);
      return {
        type: event,
        conversationId: payload.conversation_id,
        generationId: payload.generation_id,
        delta: payload.delta,
      } satisfies MessageDeltaEvent;
    }
    case "generation.usage": {
      const payload = parsePayload(generationUsageSchema, data);
      return {
        type: event,
        generationId: payload.generation_id,
        inputTokens: payload.input_tokens,
        outputTokens: payload.output_tokens,
        totalTokens: payload.total_tokens,
      } satisfies GenerationUsageEvent;
    }
    case "generation.completed": {
      const payload = parsePayload(generationCompletedSchema, data);
      return {
        type: event,
        conversationId: payload.conversation_id,
        generationId: payload.generation_id,
        assistantMessageId: payload.assistant_message_id,
        finishReason: payload.finish_reason,
      } satisfies GenerationCompletedEvent;
    }
    case "generation.error": {
      const payload = parsePayload(generationErrorSchema, data);
      return {
        type: event,
        generationId: payload.generation_id,
        kind: payload.kind,
        message: payload.message,
      } satisfies GenerationErrorEvent;
    }
    default:
      throw invalidStreamResponse();
  }
}

function takeLine(buffer: string, endOfInput: boolean): ParsedLine | null {
  for (let index = 0; index < buffer.length; index += 1) {
    const character = buffer[index];
    if (character === "\n") {
      return {
        line: buffer.slice(0, index),
        remainder: buffer.slice(index + 1),
      };
    }
    if (character !== "\r") {
      continue;
    }
    if (index + 1 === buffer.length && !endOfInput) {
      return null;
    }

    const terminatorLength = buffer[index + 1] === "\n" ? 2 : 1;
    return {
      line: buffer.slice(0, index),
      remainder: buffer.slice(index + terminatorLength),
    };
  }
  return null;
}

async function cancelBody(
  body: ReadableStream<Uint8Array> | null,
): Promise<void> {
  if (body === null) {
    return;
  }
  try {
    await body.cancel();
  } catch {
    // Cleanup must not replace the original response or streaming error.
  }
}

async function* readConversationEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ConversationStreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let eventName: string | undefined;
  let dataLines: string[] = [];
  let frameTouched = false;
  let reachedEnd = false;

  function resetFrame(): void {
    eventName = undefined;
    dataLines = [];
    frameTouched = false;
  }

  function processLine(line: string): RawServerSentEvent | null {
    if (line === "") {
      const event =
        dataLines.length > 0
          ? { event: eventName ?? "message", data: dataLines.join("\n") }
          : null;
      resetFrame();
      return event;
    }
    if (line.startsWith(":")) {
      return null;
    }

    frameTouched = true;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }

    if (field === "event") {
      eventName = value;
    } else if (field === "data") {
      dataLines.push(value);
    }
    return null;
  }

  function processBuffer(endOfInput: boolean): RawServerSentEvent[] {
    const events: RawServerSentEvent[] = [];
    let parsed = takeLine(buffer, endOfInput);
    while (parsed !== null) {
      buffer = parsed.remainder;
      const event = processLine(parsed.line);
      if (event !== null) {
        events.push(event);
      }
      parsed = takeLine(buffer, endOfInput);
    }
    return events;
  }

  try {
    while (true) {
      const result = await reader.read();
      if (result.done) {
        reachedEnd = true;
        break;
      }

      try {
        buffer += decoder.decode(result.value, { stream: true });
      } catch {
        throw invalidStreamResponse();
      }
      for (const event of processBuffer(false)) {
        yield toConversationEvent(event);
      }
    }

    try {
      buffer += decoder.decode();
    } catch {
      throw invalidStreamResponse();
    }
    for (const event of processBuffer(true)) {
      yield toConversationEvent(event);
    }
    if (buffer.length > 0 || frameTouched) {
      throw invalidStreamResponse();
    }
  } finally {
    if (!reachedEnd) {
      try {
        await reader.cancel();
      } catch {
        // Cleanup must not replace a parsing, network, or abort error.
      }
    }
    try {
      reader.releaseLock();
    } catch {
      // The stream may already be errored or locked during cancellation.
    }
  }
}

function isEventStream(response: Response): boolean {
  const contentType = response.headers.get("Content-Type");
  const mediaType = contentType?.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "text/event-stream";
}

export async function* streamConversationMessage(
  input: StreamConversationMessageInput,
): AsyncGenerator<ConversationStreamEvent> {
  const headers = new Headers({ Accept: "text/event-stream" });
  if (input.idempotencyKey !== undefined) {
    headers.set("Idempotency-Key", input.idempotencyKey);
  }

  const response = await apiResponse(
    `/conversations/${encodeURIComponent(input.conversationPublicId)}/messages`,
    {
      method: "POST",
      headers,
      body: { content: input.content, model: input.model },
      signal: input.signal,
    },
  );

  if (!isEventStream(response) || response.body === null) {
    await cancelBody(response.body);
    throw invalidStreamResponse();
  }

  yield* readConversationEvents(response.body);
}
