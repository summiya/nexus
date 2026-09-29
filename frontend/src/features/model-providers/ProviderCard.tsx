import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { NexusApiError } from "../../services/api/error";
import { setProviderCredential } from "./api";
import { ProviderConfigurationForm } from "./ProviderConfigurationForm";
import { ProviderCredentialForm } from "./ProviderCredentialForm";
import { ProviderValidationStatus } from "./ProviderValidationStatus";
import {
  modelProviderKeys,
  useDeleteProviderMutation,
  useSetProviderEnabledMutation,
  useUpdateProviderMutation,
  useValidateProviderMutation,
} from "./queries";
import type {
  ConfiguredProvider,
  ProviderCatalogItem,
  UpdateProviderInput,
} from "./types";

type OpenPanel = "edit" | "credential" | "delete" | null;
type FeedbackKind =
  | "save_failed"
  | "credential_failed"
  | "validation_failed"
  | "rate_limited"
  | "toggle_failed"
  | "delete_restricted"
  | "delete_failed";

const feedbackMessages: Record<FeedbackKind, string> = {
  save_failed: "Provider configuration could not be saved. Try again.",
  credential_failed: "Provider credential could not be saved. Try again.",
  validation_failed: "Provider validation could not be completed. Try again.",
  rate_limited: "Too many validation attempts. Try again later.",
  toggle_failed: "Provider status could not be changed. Try again.",
  delete_restricted:
    "This provider cannot be removed while it is still in use.",
  delete_failed: "Provider configuration could not be removed. Try again.",
};

export function ProviderCard({
  catalogItem,
  provider,
  canManage,
}: {
  catalogItem: ProviderCatalogItem;
  provider: ConfiguredProvider;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const update = useUpdateProviderMutation(provider.publicId);
  const validate = useValidateProviderMutation(provider.publicId);
  const setEnabled = useSetProviderEnabledMutation(provider.publicId);
  const remove = useDeleteProviderMutation(provider.publicId);
  const [credentialPending, setCredentialPending] = useState(false);
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);
  const [feedback, setFeedback] = useState<FeedbackKind | null>(null);
  const active =
    update.isPending ||
    validate.isPending ||
    setEnabled.isPending ||
    remove.isPending ||
    credentialPending;

  async function saveConfiguration(input: UpdateProviderInput) {
    setFeedback(null);
    try {
      await update.mutateAsync(input);
      setOpenPanel(null);
    } catch {
      setFeedback("save_failed");
    }
  }

  async function saveCredential(credential: string) {
    if (credentialPending) {
      return false;
    }
    setCredentialPending(true);
    setFeedback(null);
    try {
      await setProviderCredential(provider.publicId, credential);
      await queryClient.invalidateQueries({
        queryKey: modelProviderKeys.list(),
      });
      setOpenPanel(null);
      return true;
    } catch {
      setFeedback("credential_failed");
      return false;
    } finally {
      setCredentialPending(false);
    }
  }

  async function runValidation() {
    setFeedback(null);
    try {
      await validate.mutateAsync();
    } catch (error: unknown) {
      setFeedback(
        error instanceof NexusApiError && error.code === "RATE_LIMITED"
          ? "rate_limited"
          : "validation_failed",
      );
    }
  }

  async function toggleEnabled() {
    setFeedback(null);
    try {
      await setEnabled.mutateAsync(!provider.enabled);
    } catch {
      setFeedback("toggle_failed");
    }
  }

  async function confirmDelete() {
    setFeedback(null);
    try {
      await remove.mutateAsync();
      setOpenPanel(null);
    } catch (error: unknown) {
      setFeedback(
        error instanceof NexusApiError && error.code === "CONFLICT"
          ? "delete_restricted"
          : "delete_failed",
      );
    }
  }

  return (
    <article className="provider-card">
      <div className="provider-card-heading">
        <div>
          <p className="provider-kind">{catalogItem.displayName}</p>
          <h3>{provider.displayName}</h3>
        </div>
        <span
          className={
            provider.enabled ? "provider-enabled" : "provider-disabled"
          }
        >
          {provider.enabled ? "Enabled" : "Disabled"}
        </span>
      </div>

      <dl className="provider-status-grid">
        <div>
          <dt>Configuration</dt>
          <dd>Configured</dd>
          <dt>Credential</dt>
          <dd>{provider.credentialConfigured ? "Configured" : "Missing"}</dd>
        </div>
        <ProviderValidationStatus
          status={provider.validationStatus}
          lastValidatedAt={provider.lastValidatedAt}
        />
      </dl>

      {feedback ? (
        <p className="provider-feedback" role="alert">
          {feedbackMessages[feedback]}
        </p>
      ) : null}

      {canManage ? (
        <div
          className="provider-actions"
          aria-label={`${provider.displayName} actions`}
        >
          <button
            className="text-button"
            type="button"
            disabled={active}
            onClick={() => setOpenPanel(openPanel === "edit" ? null : "edit")}
          >
            Edit
          </button>
          <button
            className="text-button"
            type="button"
            disabled={active}
            onClick={() =>
              setOpenPanel(openPanel === "credential" ? null : "credential")
            }
          >
            {provider.credentialConfigured
              ? "Replace credential"
              : "Add credential"}
          </button>
          <button
            className="text-button"
            type="button"
            disabled={active}
            onClick={() => void runValidation()}
          >
            {validate.isPending ? "Validating…" : "Validate"}
          </button>
          <button
            className="text-button"
            type="button"
            disabled={active}
            onClick={() => void toggleEnabled()}
          >
            {setEnabled.isPending
              ? "Saving…"
              : provider.enabled
                ? "Disable"
                : "Enable"}
          </button>
          <button
            className="text-button provider-remove-button"
            type="button"
            disabled={active}
            onClick={() =>
              setOpenPanel(openPanel === "delete" ? null : "delete")
            }
          >
            Remove
          </button>
        </div>
      ) : null}

      {openPanel === "edit" ? (
        <ProviderConfigurationForm
          catalogItem={catalogItem}
          provider={provider}
          onSubmit={saveConfiguration}
          onCancel={() => setOpenPanel(null)}
        />
      ) : null}
      {openPanel === "credential" ? (
        <ProviderCredentialForm
          providerPublicId={provider.publicId}
          replacing={provider.credentialConfigured}
          onSubmit={saveCredential}
          onCancel={() => setOpenPanel(null)}
        />
      ) : null}
      {openPanel === "delete" ? (
        <div
          className="provider-confirmation"
          role="group"
          aria-label="Confirm provider removal"
        >
          <p>
            Remove <strong>{provider.displayName}</strong> configuration? This
            removes the organization&apos;s provider configuration.
          </p>
          <div className="provider-form-actions">
            <button
              className="primary-button provider-danger-button"
              type="button"
              disabled={active}
              onClick={() => void confirmDelete()}
            >
              {remove.isPending ? "Removing…" : "Remove provider"}
            </button>
            <button
              className="text-button"
              type="button"
              disabled={active}
              onClick={() => setOpenPanel(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
