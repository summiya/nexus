import { z } from "zod";

import { apiRequest, apiResponse } from "../../services/api/client";
import { providerTypes } from "../model-providers/types";
import {
  modelCapabilities,
  modelTypes,
  type ConfiguredModel,
  type ModelCandidate,
  type ModelDefaults,
  type ModelRegistrationInput,
  type ModelType,
} from "./types";

const uuidSchema = z.string().uuid();
const modelTypeSchema = z.enum(modelTypes);
const modelCapabilitySchema = z.enum(modelCapabilities);
const capabilitiesSchema = z
  .array(modelCapabilitySchema)
  .superRefine((capabilities, context) => {
    if (new Set(capabilities).size !== capabilities.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Model capabilities must be unique.",
      });
    }
  });

const modelFields = {
  provider_model_name: z.string().trim().min(1).max(256),
  display_name: z.string().trim().min(1).max(200),
  model_type: modelTypeSchema,
  capabilities: capabilitiesSchema,
  embedding_dimension: z.number().int().positive().nullable(),
};

function validateModelShape(
  model: {
    model_type: ModelType;
    capabilities: readonly string[];
    embedding_dimension: number | null;
  },
  context: z.RefinementCtx,
  options: { embeddingDimensionMayBeUnknown: boolean },
) {
  if (model.model_type === "chat") {
    if (model.embedding_dimension !== null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Chat model dimension must be null.",
      });
    }
    return;
  }

  if (model.capabilities.length > 0) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Non-chat models cannot declare chat capabilities.",
    });
  }
  if (
    model.model_type === "embedding" &&
    model.embedding_dimension === null &&
    !options.embeddingDimensionMayBeUnknown
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Configured embedding model dimension is required.",
    });
  }
  if (model.model_type === "reranker" && model.embedding_dimension !== null) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Reranker model dimension must be null.",
    });
  }
}

const configuredModelSchema = z
  .object({
    public_id: uuidSchema,
    provider_public_id: uuidSchema,
    provider_type: z.enum(providerTypes),
    ...modelFields,
    enabled: z.boolean(),
  })
  .strict()
  .superRefine((model, context) =>
    validateModelShape(model, context, {
      embeddingDimensionMayBeUnknown: false,
    }),
  );

const configuredModelsResponseSchema = z
  .object({ items: z.array(configuredModelSchema) })
  .strict();

const modelCandidateSchema = z
  .object(modelFields)
  .strict()
  .superRefine((model, context) =>
    validateModelShape(model, context, {
      embeddingDimensionMayBeUnknown: true,
    }),
  );

const discoveryResponseSchema = z
  .object({ items: z.array(modelCandidateSchema) })
  .strict()
  .superRefine((response, context) => {
    const names = response.items.map((item) => item.provider_model_name);
    if (new Set(names).size !== names.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Discovered model identifiers must be unique.",
      });
    }
  });

const defaultsSchema = z
  .object({
    chat: uuidSchema.nullable(),
    embedding: uuidSchema.nullable(),
    reranker: uuidSchema.nullable(),
  })
  .strict();

function invalidModelResponse(): Error {
  return new Error(
    "The Model Management service returned an invalid response.",
  );
}

function parseResponse<T>(schema: z.ZodType<T>, response: unknown): T {
  const result = schema.safeParse(response);
  if (!result.success) {
    throw invalidModelResponse();
  }
  return result.data;
}

function toConfiguredModel(
  model: z.infer<typeof configuredModelSchema>,
): ConfiguredModel {
  return {
    publicId: model.public_id,
    providerPublicId: model.provider_public_id,
    providerType: model.provider_type,
    providerModelName: model.provider_model_name,
    displayName: model.display_name,
    modelType: model.model_type,
    capabilities: Object.freeze([...model.capabilities]),
    embeddingDimension: model.embedding_dimension,
    enabled: model.enabled,
  };
}

function toModelCandidate(
  model: z.infer<typeof modelCandidateSchema>,
): ModelCandidate {
  return {
    providerModelName: model.provider_model_name,
    displayName: model.display_name,
    modelType: model.model_type,
    capabilities: Object.freeze([...model.capabilities]),
    embeddingDimension: model.embedding_dimension,
  };
}

function toDefaults(defaults: z.infer<typeof defaultsSchema>): ModelDefaults {
  return {
    chat: defaults.chat,
    embedding: defaults.embedding,
    reranker: defaults.reranker,
  };
}

export async function listConfiguredModels(): Promise<ConfiguredModel[]> {
  const response = await apiRequest<unknown>("/configured-models");
  return parseResponse(configuredModelsResponseSchema, response).items.map(
    toConfiguredModel,
  );
}

export async function discoverProviderModels(
  providerPublicId: string,
): Promise<ModelCandidate[]> {
  const response = await apiRequest<unknown>(
    `/model-providers/${encodeURIComponent(providerPublicId)}/models`,
  );
  return parseResponse(discoveryResponseSchema, response).items.map(
    toModelCandidate,
  );
}

export async function registerModels(
  providerPublicId: string,
  input: ModelRegistrationInput,
): Promise<ConfiguredModel[]> {
  const body =
    input.registrationMode === "discovered"
      ? {
          registration_mode: "discovered",
          provider_model_names: input.providerModelNames,
        }
      : {
          registration_mode: "manual",
          provider_model_name: input.providerModelName,
          display_name: input.displayName,
          model_type: input.modelType,
          capabilities: input.capabilities,
          embedding_dimension: input.embeddingDimension,
        };
  const response = await apiRequest<unknown>(
    `/model-providers/${encodeURIComponent(providerPublicId)}/configured-models`,
    { method: "POST", body },
  );
  return parseResponse(configuredModelsResponseSchema, response).items.map(
    toConfiguredModel,
  );
}

export async function setConfiguredModelEnabled(
  modelPublicId: string,
  enabled: boolean,
): Promise<ConfiguredModel> {
  const response = await apiRequest<unknown>(
    `/configured-models/${encodeURIComponent(modelPublicId)}/enabled`,
    { method: "PATCH", body: { enabled } },
  );
  return toConfiguredModel(parseResponse(configuredModelSchema, response));
}

export async function deleteConfiguredModel(
  modelPublicId: string,
): Promise<void> {
  const response = await apiResponse(
    `/configured-models/${encodeURIComponent(modelPublicId)}`,
    { method: "DELETE" },
  );
  if (response.status !== 204) {
    throw invalidModelResponse();
  }
}

export async function getModelDefaults(): Promise<ModelDefaults> {
  const response = await apiRequest<unknown>("/model-defaults");
  return toDefaults(parseResponse(defaultsSchema, response));
}

export async function setModelDefault(
  modelType: ModelType,
  modelPublicId: string,
): Promise<ModelDefaults> {
  const response = await apiRequest<unknown>(`/model-defaults/${modelType}`, {
    method: "PUT",
    body: { model_public_id: modelPublicId },
  });
  return toDefaults(parseResponse(defaultsSchema, response));
}

export async function clearModelDefault(modelType: ModelType): Promise<void> {
  const response = await apiResponse(`/model-defaults/${modelType}`, {
    method: "DELETE",
  });
  if (response.status !== 204) {
    throw invalidModelResponse();
  }
}
