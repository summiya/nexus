import { z } from "zod";

import { apiRequest } from "../../services/api/client";
import {
  conversationMessageRoles,
  generationFinishReasons,
  generationStatuses,
  type ConversationGenerationMetadata,
  type ConversationMessage,
  type ConversationSummary,
  type CreateConversationInput,
  type CreatedConversation,
} from "./types";

const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });

const conversationSummarySchema = z
  .object({
    public_id: uuidSchema,
    title: z.string().nullable(),
    created_at: timestampSchema,
    updated_at: timestampSchema,
  })
  .strict();

const conversationListResponseSchema = z
  .object({
    items: z.array(conversationSummarySchema),
  })
  .strict();

const createdConversationSchema = z
  .object({
    public_id: uuidSchema,
    organization_public_id: uuidSchema,
    created_by_user_public_id: uuidSchema,
    workspace_public_id: uuidSchema.nullable(),
    project_public_id: uuidSchema.nullable(),
    title: z.string().nullable(),
  })
  .strict();

const conversationGenerationSchema = z
  .object({
    public_id: uuidSchema,
    model: z.string(),
    status: z.enum(generationStatuses),
    finish_reason: z.enum(generationFinishReasons).nullable(),
    input_tokens: z.number().int().nonnegative(),
    output_tokens: z.number().int().nonnegative(),
    total_tokens: z.number().int().nonnegative(),
    started_at: timestampSchema.nullable(),
    completed_at: timestampSchema.nullable(),
    error_kind: z.string().nullable(),
  })
  .strict();

const conversationMessageSchema = z
  .object({
    public_id: uuidSchema,
    role: z.enum(conversationMessageRoles),
    content: z.string(),
    created_at: timestampSchema,
    generation: conversationGenerationSchema.nullable(),
  })
  .strict();

const conversationMessagesResponseSchema = z
  .object({
    items: z.array(conversationMessageSchema),
  })
  .strict();

function invalidConversationResponse(): Error {
  return new Error("The Conversation service returned an invalid response.");
}

function parseResponse<T>(schema: z.ZodType<T>, response: unknown): T {
  const result = schema.safeParse(response);
  if (!result.success) {
    throw invalidConversationResponse();
  }

  return result.data;
}

function toConversationSummary(
  response: z.infer<typeof conversationSummarySchema>,
): ConversationSummary {
  return {
    publicId: response.public_id,
    title: response.title,
    createdAt: response.created_at,
    updatedAt: response.updated_at,
  };
}

function toCreatedConversation(
  response: z.infer<typeof createdConversationSchema>,
): CreatedConversation {
  return {
    publicId: response.public_id,
    organizationPublicId: response.organization_public_id,
    createdByUserPublicId: response.created_by_user_public_id,
    workspacePublicId: response.workspace_public_id,
    projectPublicId: response.project_public_id,
    title: response.title,
  };
}

function toGenerationMetadata(
  response: z.infer<typeof conversationGenerationSchema>,
): ConversationGenerationMetadata {
  return {
    publicId: response.public_id,
    model: response.model,
    status: response.status,
    finishReason: response.finish_reason,
    inputTokens: response.input_tokens,
    outputTokens: response.output_tokens,
    totalTokens: response.total_tokens,
    startedAt: response.started_at,
    completedAt: response.completed_at,
    errorKind: response.error_kind,
  };
}

function toConversationMessage(
  response: z.infer<typeof conversationMessageSchema>,
): ConversationMessage {
  return {
    publicId: response.public_id,
    role: response.role,
    content: response.content,
    createdAt: response.created_at,
    generation:
      response.generation === null
        ? null
        : toGenerationMetadata(response.generation),
  };
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const response = await apiRequest<unknown>("/conversations", {
    method: "GET",
  });
  const parsed = parseResponse(conversationListResponseSchema, response);
  return parsed.items.map(toConversationSummary);
}

export async function createConversation(
  input?: CreateConversationInput,
): Promise<CreatedConversation> {
  const body = input?.title === undefined ? {} : { title: input.title };
  const response = await apiRequest<unknown>("/conversations", {
    method: "POST",
    body,
  });
  return toCreatedConversation(
    parseResponse(createdConversationSchema, response),
  );
}

export async function getConversationMessages(
  conversationPublicId: string,
): Promise<ConversationMessage[]> {
  const response = await apiRequest<unknown>(
    `/conversations/${encodeURIComponent(conversationPublicId)}/messages`,
    { method: "GET" },
  );
  const parsed = parseResponse(conversationMessagesResponseSchema, response);
  return parsed.items.map(toConversationMessage);
}
