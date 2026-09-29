import { z } from "zod";

import { apiRequest } from "../../services/api/client";
import {
  providerSettingNames,
  providerTypes,
  providerValidationStatuses,
  type ConfiguredProvider,
  type CreateProviderInput,
  type ModelProviderCapabilities,
  type ProviderCatalogItem,
  type ProviderValidationResult,
  type UpdateProviderInput,
} from "./types";

const timestampSchema = z.string().datetime({ offset: true });
const providerTypeSchema = z.enum(providerTypes);
const providerValidationStatusSchema = z.enum(providerValidationStatuses);
const providerSettingNameSchema = z.enum(providerSettingNames);

const capabilitiesSchema = z
  .object({
    can_read: z.boolean(),
    can_manage: z.boolean(),
  })
  .strict();

const catalogItemSchema = z
  .object({
    provider_type: providerTypeSchema,
    display_name: z.string().min(1),
    required_settings: z.array(providerSettingNameSchema),
  })
  .strict()
  .superRefine((item, context) => {
    if (
      new Set(item.required_settings).size !== item.required_settings.length
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Provider setting names must be unique.",
      });
    }
  });

const catalogResponseSchema = z
  .object({ items: z.array(catalogItemSchema) })
  .strict()
  .superRefine((response, context) => {
    const types = response.items.map((item) => item.provider_type);
    if (new Set(types).size !== types.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Provider catalog types must be unique.",
      });
    }
  });

const configuredProviderSchema = z
  .object({
    public_id: z.string().uuid(),
    provider_type: providerTypeSchema,
    display_name: z.string().min(1),
    settings: z.record(z.string()),
    enabled: z.boolean(),
    credential_configured: z.boolean(),
    validation_status: providerValidationStatusSchema,
    last_validated_at: timestampSchema.nullable(),
  })
  .strict();

const configuredProvidersResponseSchema = z
  .object({ items: z.array(configuredProviderSchema) })
  .strict();

const credentialStateSchema = z
  .object({ credential_configured: z.boolean() })
  .strict();

const validationResultSchema = z
  .object({
    status: providerValidationStatusSchema,
    last_validated_at: timestampSchema,
  })
  .strict();

function invalidProviderResponse(): Error {
  return new Error("The Model Provider service returned an invalid response.");
}

function parseResponse<T>(schema: z.ZodType<T>, response: unknown): T {
  const result = schema.safeParse(response);
  if (!result.success) {
    throw invalidProviderResponse();
  }
  return result.data;
}

function toConfiguredProvider(
  value: z.infer<typeof configuredProviderSchema>,
): ConfiguredProvider {
  return {
    publicId: value.public_id,
    providerType: value.provider_type,
    displayName: value.display_name,
    settings: Object.freeze({ ...value.settings }),
    enabled: value.enabled,
    credentialConfigured: value.credential_configured,
    validationStatus: value.validation_status,
    lastValidatedAt: value.last_validated_at,
  };
}

export async function getModelProviderCapabilities(): Promise<ModelProviderCapabilities> {
  const response = await apiRequest<unknown>("/model-providers/capabilities");
  const parsed = parseResponse(capabilitiesSchema, response);
  return { canRead: parsed.can_read, canManage: parsed.can_manage };
}

export async function listProviderCatalog(): Promise<ProviderCatalogItem[]> {
  const response = await apiRequest<unknown>("/model-providers/catalog");
  const parsed = parseResponse(catalogResponseSchema, response);
  return parsed.items.map((item) => ({
    providerType: item.provider_type,
    displayName: item.display_name,
    requiredSettings: Object.freeze([...item.required_settings]),
  }));
}

export async function listConfiguredProviders(): Promise<ConfiguredProvider[]> {
  const response = await apiRequest<unknown>("/model-providers");
  return parseResponse(configuredProvidersResponseSchema, response).items.map(
    toConfiguredProvider,
  );
}

export async function createProvider(
  input: CreateProviderInput,
): Promise<ConfiguredProvider> {
  const response = await apiRequest<unknown>("/model-providers", {
    method: "POST",
    body: {
      provider_type: input.providerType,
      display_name: input.displayName,
      settings: input.settings,
      enabled: false,
    },
  });
  return toConfiguredProvider(
    parseResponse(configuredProviderSchema, response),
  );
}

export async function updateProvider(
  providerPublicId: string,
  input: UpdateProviderInput,
): Promise<ConfiguredProvider> {
  const body: Record<string, unknown> = {};
  if (input.displayName !== undefined) {
    body.display_name = input.displayName;
  }
  if (input.settings !== undefined) {
    body.settings = input.settings;
  }
  const response = await apiRequest<unknown>(
    `/model-providers/${encodeURIComponent(providerPublicId)}`,
    { method: "PUT", body },
  );
  return toConfiguredProvider(
    parseResponse(configuredProviderSchema, response),
  );
}

export async function setProviderCredential(
  providerPublicId: string,
  credential: string,
): Promise<void> {
  const response = await apiRequest<unknown>(
    `/model-providers/${encodeURIComponent(providerPublicId)}/credential`,
    { method: "PUT", body: { credential } },
  );
  const parsed = parseResponse(credentialStateSchema, response);
  if (!parsed.credential_configured) {
    throw invalidProviderResponse();
  }
}

export async function validateProvider(
  providerPublicId: string,
): Promise<ProviderValidationResult> {
  const response = await apiRequest<unknown>(
    `/model-providers/${encodeURIComponent(providerPublicId)}/validate`,
    { method: "POST" },
  );
  const parsed = parseResponse(validationResultSchema, response);
  return { status: parsed.status, lastValidatedAt: parsed.last_validated_at };
}

export async function setProviderEnabled(
  providerPublicId: string,
  enabled: boolean,
): Promise<ConfiguredProvider> {
  const response = await apiRequest<unknown>(
    `/model-providers/${encodeURIComponent(providerPublicId)}/enabled`,
    { method: "PATCH", body: { enabled } },
  );
  return toConfiguredProvider(
    parseResponse(configuredProviderSchema, response),
  );
}

export async function deleteProvider(providerPublicId: string): Promise<void> {
  await apiRequest<void>(
    `/model-providers/${encodeURIComponent(providerPublicId)}`,
    { method: "DELETE" },
  );
}
