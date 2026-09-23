import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureApiAuthentication } from "../../services/api/client";
import { NexusApiError } from "../../services/api/error";
import {
  createConversation,
  getConversationMessages,
  listConversations,
} from "./api";

const conversationId = "11111111-1111-4111-8111-111111111111";
const secondConversationId = "22222222-2222-4222-8222-222222222222";
const organizationId = "33333333-3333-4333-8333-333333333333";
const userId = "44444444-4444-4444-8444-444444444444";
const workspaceId = "55555555-5555-4555-8555-555555555555";
const projectId = "66666666-6666-4666-8666-666666666666";
const messageId = "77777777-7777-4777-8777-777777777777";
const generationId = "88888888-8888-4888-8888-888888888888";
const createdAt = "2026-09-23T08:30:00+04:00";
const updatedAt = "2026-09-23T09:45:00+04:00";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function conversationSummary(
  overrides: Partial<{
    public_id: string;
    title: string | null;
    created_at: string;
    updated_at: string;
  }> = {},
) {
  return {
    public_id: conversationId,
    title: "Nexus architecture",
    created_at: createdAt,
    updated_at: updatedAt,
    ...overrides,
  };
}

function createdConversation(
  overrides: Partial<{
    workspace_public_id: string | null;
    project_public_id: string | null;
    title: string | null;
  }> = {},
) {
  return {
    public_id: conversationId,
    organization_public_id: organizationId,
    created_by_user_public_id: userId,
    workspace_public_id: null,
    project_public_id: null,
    title: null,
    ...overrides,
  };
}

function generationMetadata(
  overrides: Partial<{
    status: "pending" | "running" | "completed" | "failed" | "cancelled";
    finish_reason:
      "stop" | "length" | "tool_calls" | "content_filter" | "unknown" | null;
    started_at: string | null;
    completed_at: string | null;
    error_kind: string | null;
  }> = {},
) {
  return {
    public_id: generationId,
    model: "openai/gpt-5",
    status: "completed" as const,
    finish_reason: "stop" as const,
    input_tokens: 12,
    output_tokens: 8,
    total_tokens: 20,
    started_at: createdAt,
    completed_at: updatedAt,
    error_kind: null,
    ...overrides,
  };
}

function conversationMessage(
  overrides: Partial<{
    role: "system" | "user" | "assistant";
    generation: ReturnType<typeof generationMetadata> | null;
  }> = {},
) {
  return {
    public_id: messageId,
    role: "assistant" as const,
    content: "A response",
    created_at: createdAt,
    generation: null,
    ...overrides,
  };
}

describe("Conversation API", () => {
  beforeEach(() => {
    configureApiAuthentication(undefined);
  });

  afterEach(() => {
    configureApiAuthentication(undefined);
  });

  describe("listConversations", () => {
    it("uses the authenticated list endpoint and maps a valid response", async () => {
      configureApiAuthentication({
        getAccessToken: () => "access-token",
        refreshAccessToken: vi.fn(),
      });
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse({ items: [conversationSummary()] }));

      await expect(listConversations()).resolves.toEqual([
        {
          publicId: conversationId,
          title: "Nexus architecture",
          createdAt,
          updatedAt,
        },
      ]);

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/conversations",
        expect.objectContaining({ method: "GET" }),
      );
      const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
      expect(headers.get("Authorization")).toBe("Bearer access-token");
    });

    it("accepts nullable titles", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({ items: [conversationSummary({ title: null })] }),
      );

      await expect(listConversations()).resolves.toMatchObject([
        { title: null },
      ]);
    });

    it("returns an empty list", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({ items: [] }),
      );

      await expect(listConversations()).resolves.toEqual([]);
    });

    it("preserves backend ordering and timestamp strings", async () => {
      const newerCreatedAt = "2026-09-23T10:00:00Z";
      const olderCreatedAt = "2026-09-22T10:00:00Z";
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({
          items: [
            conversationSummary({
              public_id: secondConversationId,
              created_at: newerCreatedAt,
              updated_at: newerCreatedAt,
            }),
            conversationSummary({
              created_at: olderCreatedAt,
              updated_at: olderCreatedAt,
            }),
          ],
        }),
      );

      const conversations = await listConversations();

      expect(conversations.map(({ publicId }) => publicId)).toEqual([
        secondConversationId,
        conversationId,
      ]);
      expect(
        conversations.map(({ createdAt: timestamp }) => timestamp),
      ).toEqual([newerCreatedAt, olderCreatedAt]);
    });

    it("fails safely when the successful response is malformed", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({ items: [conversationSummary()], secret: "do-not-leak" }),
      );

      let thrownError: unknown;
      try {
        await listConversations();
      } catch (error) {
        thrownError = error;
      }

      expect(thrownError).toEqual(
        new Error("The Conversation service returned an invalid response."),
      );
      expect(String(thrownError)).not.toContain("do-not-leak");
    });
  });

  describe("createConversation", () => {
    it.each([
      ["without input", undefined],
      ["with an undefined title", { title: undefined }],
    ])("sends an empty object %s", async (_description, input) => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(createdConversation(), 201));

      await createConversation(input);

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/conversations",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({}),
        }),
      );
    });

    it.each([
      [null, { title: null }],
      ["A focused title", { title: "A focused title" }],
    ])("sends the requested title value %s", async (title, expectedBody) => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse(createdConversation({ title }), 201));

      await createConversation({ title });

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/conversations",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify(expectedBody),
        }),
      );
    });

    it("maps nullable and populated scope identifiers", async () => {
      vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(jsonResponse(createdConversation(), 201))
        .mockResolvedValueOnce(
          jsonResponse(
            createdConversation({
              workspace_public_id: workspaceId,
              project_public_id: projectId,
              title: "Scoped",
            }),
            201,
          ),
        );

      await expect(createConversation()).resolves.toMatchObject({
        workspacePublicId: null,
        projectPublicId: null,
      });
      await expect(createConversation()).resolves.toMatchObject({
        workspacePublicId: workspaceId,
        projectPublicId: projectId,
      });
    });

    it("fails safely when the successful response is malformed", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse(
          { ...createdConversation(), public_id: "not-a-uuid" },
          201,
        ),
      );

      await expect(createConversation()).rejects.toThrow(
        "The Conversation service returned an invalid response.",
      );
    });
  });

  describe("getConversationMessages", () => {
    it("encodes the conversation identifier in the message-history path", async () => {
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(jsonResponse({ items: [] }));

      await getConversationMessages("conversation/id");

      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/conversations/conversation%2Fid/messages",
        expect.objectContaining({ method: "GET" }),
      );
    });

    it.each(["system", "user", "assistant"] as const)(
      "parses the %s message role",
      async (role) => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(
          jsonResponse({ items: [conversationMessage({ role })] }),
        );

        await expect(
          getConversationMessages(conversationId),
        ).resolves.toMatchObject([{ role, generation: null }]);
      },
    );

    it("maps complete generation metadata and preserves timestamps", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({
          items: [conversationMessage({ generation: generationMetadata() })],
        }),
      );

      await expect(getConversationMessages(conversationId)).resolves.toEqual([
        {
          publicId: messageId,
          role: "assistant",
          content: "A response",
          createdAt,
          generation: {
            publicId: generationId,
            model: "openai/gpt-5",
            status: "completed",
            finishReason: "stop",
            inputTokens: 12,
            outputTokens: 8,
            totalTokens: 20,
            startedAt: createdAt,
            completedAt: updatedAt,
            errorKind: null,
          },
        },
      ]);
    });

    it("parses every supported generation status and finish reason", async () => {
      const statuses = [
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
      ] as const;
      const finishReasons = [
        "stop",
        "length",
        "tool_calls",
        "content_filter",
        "unknown",
      ] as const;
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({
          items: statuses.map((status, index) => ({
            ...conversationMessage({
              generation: generationMetadata({
                status,
                finish_reason: finishReasons[index],
              }),
            }),
            public_id: `${index + 1}0000000-0000-4000-8000-000000000000`,
          })),
        }),
      );

      const messages = await getConversationMessages(conversationId);

      expect(messages.map((message) => message.generation?.status)).toEqual(
        statuses,
      );
      expect(
        messages.map((message) => message.generation?.finishReason),
      ).toEqual(finishReasons);
    });

    it("accepts nullable generation lifecycle metadata", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({
          items: [
            conversationMessage({
              generation: generationMetadata({
                finish_reason: null,
                started_at: null,
                completed_at: null,
                error_kind: "stream_processing_failure",
              }),
            }),
          ],
        }),
      );

      await expect(
        getConversationMessages(conversationId),
      ).resolves.toMatchObject([
        {
          generation: {
            finishReason: null,
            startedAt: null,
            completedAt: null,
            errorKind: "stream_processing_failure",
          },
        },
      ]);
    });

    it("returns an empty message history", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({ items: [] }),
      );

      await expect(getConversationMessages(conversationId)).resolves.toEqual(
        [],
      );
    });

    it("fails safely for unsupported generation enum values", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({
          items: [
            {
              ...conversationMessage(),
              generation: {
                ...generationMetadata(),
                status: "unknown-status",
              },
            },
          ],
        }),
      );

      await expect(getConversationMessages(conversationId)).rejects.toThrow(
        "The Conversation service returned an invalid response.",
      );
    });

    it("fails safely when the successful response is malformed", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        jsonResponse({
          items: [{ ...conversationMessage(), unexpected: "do-not-leak" }],
        }),
      );

      await expect(getConversationMessages(conversationId)).rejects.toThrow(
        "The Conversation service returned an invalid response.",
      );
    });
  });

  it("propagates backend API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "SERVICE_UNAVAILABLE",
            message: "Conversation service unavailable",
            request_id: "request-123",
          },
        },
        503,
      ),
    );

    await expect(listConversations()).rejects.toEqual(
      new NexusApiError(
        "Conversation service unavailable",
        503,
        "SERVICE_UNAVAILABLE",
        "request-123",
      ),
    );
  });

  it("propagates network errors unchanged", async () => {
    const networkError = new TypeError("Failed to fetch");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(networkError);

    await expect(listConversations()).rejects.toBe(networkError);
  });
});
