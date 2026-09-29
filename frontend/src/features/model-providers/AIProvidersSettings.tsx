import { useState } from "react";

import { ProviderCard } from "./ProviderCard";
import { ProviderConfigurationForm } from "./ProviderConfigurationForm";
import {
  useConfiguredProvidersQuery,
  useCreateProviderMutation,
  useModelProviderCapabilitiesQuery,
  useProviderCatalogQuery,
} from "./queries";
import type {
  ConfiguredProvider,
  CreateProviderInput,
  ProviderCatalogItem,
  ProviderType,
} from "./types";

export function AIProvidersSettings() {
  const capabilities = useModelProviderCapabilitiesQuery();
  const canRead = capabilities.data?.canRead === true;
  const canManage = capabilities.data?.canManage === true;
  const catalog = useProviderCatalogQuery(canRead);
  const providers = useConfiguredProvidersQuery(canRead);
  const create = useCreateProviderMutation();
  const [creatingType, setCreatingType] = useState<ProviderType | null>(null);
  const [creationFailed, setCreationFailed] = useState(false);

  async function createConfiguration(input: CreateProviderInput) {
    setCreationFailed(false);
    try {
      await create.mutateAsync(input);
      setCreatingType(null);
    } catch {
      setCreationFailed(true);
    }
  }

  if (capabilities.isPending) {
    return <p role="status">Checking provider access…</p>;
  }
  if (capabilities.isError) {
    return (
      <ProviderPageError
        message="Provider access is temporarily unavailable."
        retrying={capabilities.isFetching}
        onRetry={() => void capabilities.refetch()}
      />
    );
  }
  if (!canRead) {
    return (
      <div className="provider-page-state">
        <h2>AI Providers</h2>
        <p>You do not have permission to view AI provider configuration.</p>
      </div>
    );
  }
  if (catalog.isPending || providers.isPending) {
    return <p role="status">Loading AI providers…</p>;
  }
  if (catalog.isError || providers.isError) {
    return (
      <ProviderPageError
        message="AI provider configuration is temporarily unavailable."
        retrying={catalog.isFetching || providers.isFetching}
        onRetry={() => {
          void catalog.refetch();
          void providers.refetch();
        }}
      />
    );
  }

  return (
    <section className="ai-providers" aria-labelledby="ai-providers-heading">
      <header className="settings-section-heading">
        <p className="eyebrow">Organization settings</p>
        <h2 id="ai-providers-heading">AI Providers</h2>
        <p>
          Configure the AI providers available to this organization. Credentials
          are write-only and are never shown again.
        </p>
      </header>

      <div className="provider-groups">
        {catalog.data.map((item) => {
          const configured = providers.data.filter(
            (provider) => provider.providerType === item.providerType,
          );
          return (
            <ProviderGroup
              key={item.providerType}
              catalogItem={item}
              configuredProviders={configured}
              canManage={canManage}
              creating={creatingType === item.providerType}
              creationPending={create.isPending}
              creationFailed={
                creationFailed && creatingType === item.providerType
              }
              onStartCreate={() => {
                setCreationFailed(false);
                setCreatingType(item.providerType);
              }}
              onCancelCreate={() => {
                setCreationFailed(false);
                setCreatingType(null);
              }}
              onCreate={createConfiguration}
            />
          );
        })}
      </div>
    </section>
  );
}

function ProviderGroup({
  catalogItem,
  configuredProviders,
  canManage,
  creating,
  creationPending,
  creationFailed,
  onStartCreate,
  onCancelCreate,
  onCreate,
}: {
  catalogItem: ProviderCatalogItem;
  configuredProviders: readonly ConfiguredProvider[];
  canManage: boolean;
  creating: boolean;
  creationPending: boolean;
  creationFailed: boolean;
  onStartCreate: () => void;
  onCancelCreate: () => void;
  onCreate: (input: CreateProviderInput) => Promise<void>;
}) {
  const items = configuredProviders ?? [];
  return (
    <section
      className="provider-group"
      aria-labelledby={`provider-${catalogItem.providerType}`}
    >
      <div className="provider-group-heading">
        <div>
          <h3 id={`provider-${catalogItem.providerType}`}>
            {catalogItem.displayName}
          </h3>
          <p>
            {items.length === 0
              ? "Not configured"
              : `${items.length} configured`}
          </p>
        </div>
        {canManage && !creating ? (
          <button
            className="text-button"
            type="button"
            disabled={creationPending}
            onClick={onStartCreate}
          >
            Add configuration
          </button>
        ) : null}
      </div>

      {items.map((provider) => (
        <ProviderCard
          key={provider.publicId}
          catalogItem={catalogItem}
          provider={provider}
          canManage={canManage}
        />
      ))}

      {creating ? (
        <div className="provider-card provider-create-card">
          <h4>Configure {catalogItem.displayName}</h4>
          {creationFailed ? (
            <p className="provider-feedback" role="alert">
              Provider configuration could not be created. Try again.
            </p>
          ) : null}
          <ProviderConfigurationForm
            catalogItem={catalogItem}
            onSubmit={(input) =>
              "providerType" in input ? onCreate(input) : Promise.resolve()
            }
            onCancel={onCancelCreate}
          />
        </div>
      ) : null}
    </section>
  );
}

function ProviderPageError({
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
