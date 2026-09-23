export const conversationMessageRoles = [
  "system",
  "user",
  "assistant",
] as const;

export type ConversationMessageRole = (typeof conversationMessageRoles)[number];

export const generationStatuses = [
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
] as const;

export type GenerationStatus = (typeof generationStatuses)[number];

export const generationFinishReasons = [
  "stop",
  "length",
  "tool_calls",
  "content_filter",
  "unknown",
] as const;

export type GenerationFinishReason = (typeof generationFinishReasons)[number];

export interface ConversationSummary {
  publicId: string;
  title: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CreateConversationInput {
  title?: string | null;
}

export interface CreatedConversation {
  publicId: string;
  organizationPublicId: string;
  createdByUserPublicId: string;
  workspacePublicId: string | null;
  projectPublicId: string | null;
  title: string | null;
}

export interface ConversationGenerationMetadata {
  publicId: string;
  model: string;
  status: GenerationStatus;
  finishReason: GenerationFinishReason | null;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  startedAt: string | null;
  completedAt: string | null;
  errorKind: string | null;
}

export interface ConversationMessage {
  publicId: string;
  role: ConversationMessageRole;
  content: string;
  createdAt: string;
  generation: ConversationGenerationMetadata | null;
}

export interface StreamConversationMessageInput {
  conversationPublicId: string;
  content: string;
  model: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface GenerationStartedEvent {
  type: "generation.started";
  conversationId: string;
  generationId: string;
  model: string;
}

export interface MessageDeltaEvent {
  type: "message.delta";
  conversationId: string;
  generationId: string;
  delta: string;
}

export interface GenerationUsageEvent {
  type: "generation.usage";
  generationId: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface GenerationCompletedEvent {
  type: "generation.completed";
  conversationId: string;
  generationId: string;
  assistantMessageId: string;
  finishReason: GenerationFinishReason;
}

export interface GenerationErrorEvent {
  type: "generation.error";
  generationId: string;
  kind: string;
  message: string;
}

export type ConversationStreamEvent =
  | GenerationStartedEvent
  | MessageDeltaEvent
  | GenerationUsageEvent
  | GenerationCompletedEvent
  | GenerationErrorEvent;
