import type { ConfiguredProvider } from "../model-providers";
import type { ConfiguredModel, ModelType } from "./types";

export const providerReadinessMessage =
  "Enable and successfully validate this provider and configure its credential first.";

export function isProviderVisiblyReady(provider: ConfiguredProvider): boolean {
  return (
    provider.enabled &&
    provider.validationStatus === "valid" &&
    provider.credentialConfigured
  );
}

export function isVisibleDefaultCandidate(
  model: ConfiguredModel,
  provider: ConfiguredProvider | undefined,
  modelType: ModelType,
): boolean {
  if (
    provider === undefined ||
    !isProviderVisiblyReady(provider) ||
    !model.enabled ||
    model.modelType !== modelType
  ) {
    return false;
  }
  return modelType !== "chat" || model.capabilities.includes("streaming");
}
