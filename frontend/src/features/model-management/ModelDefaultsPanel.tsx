import { useState } from "react";

import type { ConfiguredProvider } from "../model-providers";
import { isVisibleDefaultCandidate } from "./eligibility";
import {
  useClearModelDefaultMutation,
  useSetModelDefaultMutation,
} from "./queries";
import {
  modelTypes,
  type ConfiguredModel,
  type ModelDefaults,
  type ModelType,
} from "./types";

const modelTypeLabels: Record<ModelType, string> = {
  chat: "Chat",
  embedding: "Embedding",
  reranker: "Reranker",
};

export function ModelDefaultsPanel({
  defaults,
  models,
  providers,
  canManage,
}: {
  defaults: ModelDefaults;
  models: readonly ConfiguredModel[];
  providers: readonly ConfiguredProvider[];
  canManage: boolean;
}) {
  const providersById = new Map(
    providers.map((provider) => [provider.publicId, provider]),
  );

  return (
    <section
      className="model-defaults"
      aria-labelledby="model-defaults-heading"
    >
      <div>
        <h3 id="model-defaults-heading">Organization defaults</h3>
        <p>
          Used when an application request does not select a model explicitly.
        </p>
      </div>
      <div className="model-default-grid">
        {modelTypes.map((modelType) => (
          <DefaultSelector
            key={modelType}
            modelType={modelType}
            currentModelPublicId={defaults[modelType]}
            models={models}
            providersById={providersById}
            canManage={canManage}
          />
        ))}
      </div>
    </section>
  );
}

function DefaultSelector({
  modelType,
  currentModelPublicId,
  models,
  providersById,
  canManage,
}: {
  modelType: ModelType;
  currentModelPublicId: string | null;
  models: readonly ConfiguredModel[];
  providersById: ReadonlyMap<string, ConfiguredProvider>;
  canManage: boolean;
}) {
  const setDefault = useSetModelDefaultMutation();
  const clearDefault = useClearModelDefaultMutation();
  const [failed, setFailed] = useState(false);
  const candidates = models.filter((model) =>
    isVisibleDefaultCandidate(
      model,
      providersById.get(model.providerPublicId),
      modelType,
    ),
  );
  const currentModel = models.find(
    (model) => model.publicId === currentModelPublicId,
  );
  const currentIsSelectable = candidates.some(
    (model) => model.publicId === currentModelPublicId,
  );
  const active = setDefault.isPending || clearDefault.isPending;

  async function changeDefault(value: string) {
    setFailed(false);
    try {
      if (value === "") {
        await clearDefault.mutateAsync(modelType);
      } else {
        await setDefault.mutateAsync({ modelType, modelPublicId: value });
      }
    } catch {
      setFailed(true);
    }
  }

  const label = `Default ${modelTypeLabels[modelType]} Model`;
  return (
    <div className="model-default-field">
      <label htmlFor={`default-model-${modelType}`}>{label}</label>
      {canManage ? (
        <select
          id={`default-model-${modelType}`}
          value={currentModelPublicId ?? ""}
          disabled={active}
          onChange={(event) => void changeDefault(event.target.value)}
        >
          <option value="">None</option>
          {currentModelPublicId !== null && !currentIsSelectable ? (
            <option value={currentModelPublicId} disabled>
              {currentModel?.displayName ?? "Current model"} — unavailable
            </option>
          ) : null}
          {candidates.map((model) => {
            const provider = providersById.get(model.providerPublicId);
            return (
              <option key={model.publicId} value={model.publicId}>
                {model.displayName} — {provider?.displayName ?? "Provider"}
              </option>
            );
          })}
        </select>
      ) : (
        <p>
          {currentModelPublicId === null
            ? "None"
            : (currentModel?.displayName ?? "Unavailable model")}
        </p>
      )}
      {candidates.length === 0 ? (
        <small>No eligible {modelType} model is available.</small>
      ) : null}
      {failed ? (
        <p className="provider-feedback" role="alert">
          The default model could not be changed. Refresh and try again.
        </p>
      ) : null}
    </div>
  );
}
