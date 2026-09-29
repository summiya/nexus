import { ConfiguredModelCard } from "./ConfiguredModelCard";
import {
  isProviderVisiblyReady,
  providerReadinessMessage,
} from "./eligibility";
import { ManualModelRegistrationForm } from "./ManualModelRegistrationForm";
import { ModelDefaultsPanel } from "./ModelDefaultsPanel";
import { ModelDiscoveryPanel } from "./ModelDiscoveryPanel";
import { useConfiguredModelsQuery, useModelDefaultsQuery } from "./queries";
import { modelTypes, type ConfiguredModel, type ModelType } from "./types";
import {
  useConfiguredProvidersQuery,
  useModelProviderCapabilitiesQuery,
  type ConfiguredProvider,
  type ProviderType,
} from "../model-providers";

const automaticDiscoveryProviders = new Set<ProviderType>([
  "openai",
  "anthropic",
  "gemini",
]);

const manualRegistrationProviders = new Set<ProviderType>([
  "azure_openai",
  "openai_compatible",
]);

const providerTypeLabels: Record<ProviderType, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  azure_openai: "Azure OpenAI",
  gemini: "Gemini",
  openai_compatible: "OpenAI-compatible",
};

export function AIModelsSettings() {
  const capabilities = useModelProviderCapabilitiesQuery();
  const canRead = capabilities.data?.canRead === true;
  const canManage = capabilities.data?.canManage === true;
  const providers = useConfiguredProvidersQuery(canRead);
  const models = useConfiguredModelsQuery(canRead);
  const defaults = useModelDefaultsQuery(canRead);

  if (capabilities.isPending) {
    return <p role="status">Checking model access…</p>;
  }
  if (capabilities.isError) {
    return (
      <ModelsPageError
        message="Model access is temporarily unavailable."
        retrying={capabilities.isFetching}
        onRetry={() => void capabilities.refetch()}
      />
    );
  }
  if (!canRead) {
    return (
      <div className="provider-page-state">
        <h2>AI Models</h2>
        <p>You do not have permission to view AI model configuration.</p>
      </div>
    );
  }
  if (providers.isPending || models.isPending || defaults.isPending) {
    return <p role="status">Loading AI models…</p>;
  }
  if (providers.isError || models.isError || defaults.isError) {
    return (
      <ModelsPageError
        message="AI model configuration is temporarily unavailable."
        retrying={
          providers.isFetching || models.isFetching || defaults.isFetching
        }
        onRetry={() => {
          void providers.refetch();
          void models.refetch();
          void defaults.refetch();
        }}
      />
    );
  }

  const providerIds = new Set(
    providers.data.map((provider) => provider.publicId),
  );
  const modelIds = new Set(models.data.map((model) => model.publicId));
  const defaultIds = modelTypes
    .map((modelType) => defaults.data[modelType])
    .filter((modelId): modelId is string => modelId !== null);
  if (
    models.data.some((model) => !providerIds.has(model.providerPublicId)) ||
    defaultIds.some((modelId) => !modelIds.has(modelId))
  ) {
    return (
      <ModelsPageError
        message="AI model configuration is temporarily unavailable."
        retrying={false}
        onRetry={() => {
          void providers.refetch();
          void models.refetch();
          void defaults.refetch();
        }}
      />
    );
  }

  return (
    <section className="ai-models" aria-labelledby="ai-models-heading">
      <header className="settings-section-heading">
        <p className="eyebrow">Organization settings</p>
        <h2 id="ai-models-heading">AI Models</h2>
        <p>
          Register provider models and choose organization defaults. Runtime
          requests revalidate model and provider eligibility.
        </p>
      </header>

      <ModelDefaultsPanel
        defaults={defaults.data}
        models={models.data}
        providers={providers.data}
        canManage={canManage}
      />

      {providers.data.length === 0 ? (
        <div className="provider-page-state">
          <p>Configure an AI provider before registering models.</p>
        </div>
      ) : (
        <div className="provider-groups">
          {providers.data.map((provider) => (
            <ProviderModelsSection
              key={provider.publicId}
              provider={provider}
              models={models.data.filter(
                (model) => model.providerPublicId === provider.publicId,
              )}
              defaults={defaults.data}
              canManage={canManage}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ProviderModelsSection({
  provider,
  models,
  defaults,
  canManage,
}: {
  provider: ConfiguredProvider;
  models: readonly ConfiguredModel[];
  defaults: Record<ModelType, string | null>;
  canManage: boolean;
}) {
  const providerReady = isProviderVisiblyReady(provider);
  return (
    <section
      className="provider-group model-provider-group"
      aria-labelledby={`model-provider-${provider.publicId}`}
    >
      <div className="provider-group-heading">
        <div>
          <p className="provider-kind">
            {providerTypeLabels[provider.providerType]}
          </p>
          <h3 id={`model-provider-${provider.publicId}`}>
            {provider.displayName}
          </h3>
          <p>
            {models.length === 0
              ? "No configured models."
              : `${models.length} configured`}
          </p>
        </div>
        <span
          className={providerReady ? "provider-enabled" : "provider-disabled"}
        >
          {providerReady ? "Ready" : "Not ready"}
        </span>
      </div>

      <div className="model-card-list">
        {models.map((model) => (
          <ConfiguredModelCard
            key={model.publicId}
            model={model}
            defaultTypes={modelTypes.filter(
              (modelType) => defaults[modelType] === model.publicId,
            )}
            canManage={canManage}
            providerReady={providerReady}
            providerReadinessMessage={providerReadinessMessage}
          />
        ))}
      </div>

      {canManage && automaticDiscoveryProviders.has(provider.providerType) ? (
        <ModelDiscoveryPanel
          providerPublicId={provider.publicId}
          providerRevision={provider.lastValidatedAt}
          configuredModels={models}
          providerReady={providerReady}
          providerReadinessMessage={providerReadinessMessage}
        />
      ) : null}
      {canManage && manualRegistrationProviders.has(provider.providerType) ? (
        <ManualModelRegistrationForm
          providerPublicId={provider.publicId}
          providerType={provider.providerType}
          providerReady={providerReady}
          providerReadinessMessage={providerReadinessMessage}
        />
      ) : null}
    </section>
  );
}

function ModelsPageError({
  message,
  retrying,
  onRetry,
}: {
  message: string;
  retrying: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="provider-page-state">
      <p role="alert">{message}</p>
      <button
        className="text-button"
        type="button"
        disabled={retrying}
        onClick={onRetry}
      >
        {retrying ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
