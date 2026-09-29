import type { ProviderType } from "../model-providers";

export const modelTypes = ["chat", "embedding", "reranker"] as const;

export type ModelType = (typeof modelTypes)[number];

export const modelCapabilities = [
  "streaming",
  "tools",
  "vision",
  "structured_output",
] as const;

export type ModelCapability = (typeof modelCapabilities)[number];

export interface ConfiguredModel {
  publicId: string;
  providerPublicId: string;
  providerType: ProviderType;
  providerModelName: string;
  displayName: string;
  modelType: ModelType;
  capabilities: readonly ModelCapability[];
  embeddingDimension: number | null;
  enabled: boolean;
}

export interface ModelCandidate {
  providerModelName: string;
  displayName: string;
  modelType: ModelType;
  capabilities: readonly ModelCapability[];
  embeddingDimension: number | null;
}

export interface ModelDefaults {
  chat: string | null;
  embedding: string | null;
  reranker: string | null;
}

export interface DiscoveredModelRegistrationInput {
  registrationMode: "discovered";
  providerModelNames: string[];
}

export interface ManualModelRegistrationInput {
  registrationMode: "manual";
  providerModelName: string;
  displayName: string;
  modelType: ModelType;
  capabilities: ModelCapability[];
  embeddingDimension: number | null;
}

export type ModelRegistrationInput =
  DiscoveredModelRegistrationInput | ManualModelRegistrationInput;
