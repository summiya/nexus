import { useState } from "react";

import { NexusApiError } from "../../services/api/error";
import {
  useDeleteConfiguredModelMutation,
  useSetConfiguredModelEnabledMutation,
} from "./queries";
import type { ConfiguredModel, ModelType } from "./types";

const modelTypeLabels: Record<ModelType, string> = {
  chat: "Chat",
  embedding: "Embedding",
  reranker: "Reranker",
};

const capabilityLabels = {
  streaming: "Streaming",
  tools: "Tools",
  vision: "Vision",
  structured_output: "Structured output",
} as const;

type Feedback = "toggle_failed" | "delete_restricted" | "delete_failed";

const feedbackMessages: Record<Feedback, string> = {
  toggle_failed: "Model status could not be changed. Try again.",
  delete_restricted: "This model cannot be removed while it is still in use.",
  delete_failed: "The configured model could not be removed. Try again.",
};

export function ConfiguredModelCard({
  model,
  defaultTypes,
  canManage,
  providerReady,
  providerReadinessMessage,
}: {
  model: ConfiguredModel;
  defaultTypes: readonly ModelType[];
  canManage: boolean;
  providerReady: boolean;
  providerReadinessMessage: string;
}) {
  const setEnabled = useSetConfiguredModelEnabledMutation();
  const remove = useDeleteConfiguredModelMutation();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const active = setEnabled.isPending || remove.isPending;
  const enableBlocked = !model.enabled && !providerReady;

  async function toggleEnabled() {
    setFeedback(null);
    try {
      await setEnabled.mutateAsync({
        modelPublicId: model.publicId,
        enabled: !model.enabled,
      });
    } catch {
      setFeedback("toggle_failed");
    }
  }

  async function confirmDelete() {
    setFeedback(null);
    try {
      await remove.mutateAsync(model.publicId);
      setConfirmingDelete(false);
    } catch (error: unknown) {
      setFeedback(
        error instanceof NexusApiError && error.code === "CONFLICT"
          ? "delete_restricted"
          : "delete_failed",
      );
    }
  }

  return (
    <article className="model-card">
      <div className="model-card-heading">
        <div>
          <p className="provider-kind">{modelTypeLabels[model.modelType]}</p>
          <h4>{model.displayName}</h4>
          <p className="model-provider-name">{model.providerModelName}</p>
        </div>
        <span
          className={model.enabled ? "provider-enabled" : "provider-disabled"}
        >
          {model.enabled ? "Enabled" : "Disabled"}
        </span>
      </div>

      <div className="model-metadata">
        {model.capabilities.map((capability) => (
          <span key={capability}>{capabilityLabels[capability]}</span>
        ))}
        {model.embeddingDimension !== null ? (
          <span>{model.embeddingDimension} dimensions</span>
        ) : null}
        {defaultTypes.map((modelType) => (
          <span className="model-default-badge" key={modelType}>
            Default {modelType}
          </span>
        ))}
      </div>

      {feedback ? (
        <p className="provider-feedback" role="alert">
          {feedbackMessages[feedback]}
        </p>
      ) : null}
      {enableBlocked ? (
        <p className="model-readiness-note">{providerReadinessMessage}</p>
      ) : null}

      {canManage ? (
        <div className="provider-actions">
          <button
            className="text-button"
            type="button"
            disabled={active || enableBlocked}
            onClick={() => void toggleEnabled()}
          >
            {setEnabled.isPending
              ? "Saving…"
              : model.enabled
                ? "Disable"
                : "Enable"}
          </button>
          <button
            className="text-button provider-remove-button"
            type="button"
            disabled={active}
            onClick={() => setConfirmingDelete(true)}
          >
            Remove
          </button>
        </div>
      ) : null}

      {confirmingDelete ? (
        <div
          className="provider-confirmation"
          role="group"
          aria-label="Confirm model removal"
        >
          <p>
            Remove <strong>{model.displayName}</strong>? This removes the
            organization&apos;s configured model entry.
          </p>
          <div className="provider-form-actions">
            <button
              className="primary-button provider-danger-button"
              type="button"
              disabled={active}
              onClick={() => void confirmDelete()}
            >
              {remove.isPending ? "Removing…" : "Remove model"}
            </button>
            <button
              className="text-button"
              type="button"
              disabled={active}
              onClick={() => setConfirmingDelete(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
