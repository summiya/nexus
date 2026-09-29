export const providerTypes = [
  "openai",
  "anthropic",
  "azure_openai",
  "gemini",
  "openai_compatible",
] as const;

export type ProviderType = (typeof providerTypes)[number];

export const providerValidationStatuses = [
  "unvalidated",
  "valid",
  "invalid_credentials",
  "unreachable",
  "unsupported_configuration",
] as const;

export type ProviderValidationStatus =
  (typeof providerValidationStatuses)[number];

export const providerSettingNames = [
  "endpoint",
  "api_version",
  "base_url",
] as const;

export type ProviderSettingName = (typeof providerSettingNames)[number];

export interface ModelProviderCapabilities {
  canRead: boolean;
  canManage: boolean;
}

export interface ProviderCatalogItem {
  providerType: ProviderType;
  displayName: string;
  requiredSettings: readonly ProviderSettingName[];
}

export interface ConfiguredProvider {
  publicId: string;
  providerType: ProviderType;
  displayName: string;
  settings: Readonly<Record<string, string>>;
  enabled: boolean;
  credentialConfigured: boolean;
  validationStatus: ProviderValidationStatus;
  lastValidatedAt: string | null;
}

export interface CreateProviderInput {
  providerType: ProviderType;
  displayName: string;
  settings: Record<string, string>;
}

export interface UpdateProviderInput {
  displayName?: string;
  settings?: Record<string, string>;
}

export interface ProviderValidationResult {
  status: ProviderValidationStatus;
  lastValidatedAt: string;
}
