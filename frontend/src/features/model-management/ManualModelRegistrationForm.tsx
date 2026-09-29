import { useState } from "react";
import { useForm } from "react-hook-form";

import type { ProviderType } from "../model-providers";
import { useRegisterModelsMutation } from "./queries";
import {
  modelCapabilities,
  modelTypes,
  type ModelCapability,
  type ModelType,
} from "./types";

const PROVIDER_MODEL_NAME_MAX_LENGTH = 256;
const DISPLAY_NAME_MAX_LENGTH = 200;

interface ManualModelValues {
  providerModelName: string;
  displayName: string;
  modelType: ModelType;
  capabilities: ModelCapability[];
  embeddingDimension: string;
}

export function ManualModelRegistrationForm({
  providerPublicId,
  providerType,
  providerReady,
  providerReadinessMessage,
}: {
  providerPublicId: string;
  providerType: ProviderType;
  providerReady: boolean;
  providerReadinessMessage: string;
}) {
  const registration = useRegisterModelsMutation(providerPublicId);
  const [open, setOpen] = useState(false);
  const [registrationFailed, setRegistrationFailed] = useState(false);
  const form = useForm<ManualModelValues>({
    defaultValues: {
      providerModelName: "",
      displayName: "",
      modelType: "chat",
      capabilities: [],
      embeddingDimension: "",
    },
  });
  const modelType = form.watch("modelType");

  function resetAndClose() {
    form.reset();
    setRegistrationFailed(false);
    setOpen(false);
  }

  const submit = form.handleSubmit(async (values) => {
    if (!providerReady) {
      return;
    }
    setRegistrationFailed(false);
    const dimension =
      values.modelType === "embedding"
        ? Number(values.embeddingDimension)
        : null;
    try {
      await registration.mutateAsync({
        registrationMode: "manual",
        providerModelName: values.providerModelName.trim(),
        displayName: values.displayName.trim(),
        modelType: values.modelType,
        capabilities: values.modelType === "chat" ? values.capabilities : [],
        embeddingDimension: dimension,
      });
      resetAndClose();
    } catch {
      setRegistrationFailed(true);
    }
  });

  const invocationLabel =
    providerType === "azure_openai"
      ? "Azure deployment name"
      : "Provider model identifier";

  return (
    <section className="model-registration-panel" aria-label="Add model">
      {!providerReady ? (
        <p className="model-readiness-note">{providerReadinessMessage}</p>
      ) : null}
      {!open ? (
        <button
          className="text-button"
          type="button"
          disabled={!providerReady}
          onClick={() => setOpen(true)}
        >
          {providerType === "azure_openai" ? "Add deployment" : "Add model"}
        </button>
      ) : (
        <form className="provider-form" onSubmit={submit} noValidate>
          <p className="model-declaration-note">
            Model metadata is administrator-declared and is verified only when
            the model is invoked.
          </p>
          <div className="form-field">
            <label htmlFor={`manual-model-name-${providerPublicId}`}>
              {invocationLabel}
            </label>
            <input
              id={`manual-model-name-${providerPublicId}`}
              maxLength={PROVIDER_MODEL_NAME_MAX_LENGTH}
              aria-invalid={Boolean(form.formState.errors.providerModelName)}
              {...form.register("providerModelName", {
                validate: (value) =>
                  value.trim().length > 0 || `${invocationLabel} is required.`,
              })}
            />
            {form.formState.errors.providerModelName ? (
              <p className="form-error" role="alert">
                {form.formState.errors.providerModelName.message}
              </p>
            ) : null}
          </div>
          <div className="form-field">
            <label htmlFor={`manual-model-display-${providerPublicId}`}>
              Display name
            </label>
            <input
              id={`manual-model-display-${providerPublicId}`}
              maxLength={DISPLAY_NAME_MAX_LENGTH}
              aria-invalid={Boolean(form.formState.errors.displayName)}
              {...form.register("displayName", {
                validate: (value) =>
                  value.trim().length > 0 || "Display name is required.",
              })}
            />
            {form.formState.errors.displayName ? (
              <p className="form-error" role="alert">
                {form.formState.errors.displayName.message}
              </p>
            ) : null}
          </div>
          <div className="form-field">
            <label htmlFor={`manual-model-type-${providerPublicId}`}>
              Model type
            </label>
            <select
              id={`manual-model-type-${providerPublicId}`}
              {...form.register("modelType", {
                onChange: () => {
                  form.setValue("capabilities", []);
                  form.setValue("embeddingDimension", "");
                },
              })}
            >
              {modelTypes.map((type) => (
                <option key={type} value={type}>
                  {type[0].toUpperCase() + type.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {modelType === "chat" ? (
            <fieldset className="model-capability-fields">
              <legend>Capabilities</legend>
              {modelCapabilities.map((capability) => (
                <label key={capability}>
                  <input
                    type="checkbox"
                    value={capability}
                    {...form.register("capabilities")}
                  />
                  {capability.replace("_", " ")}
                </label>
              ))}
            </fieldset>
          ) : null}

          {modelType === "embedding" ? (
            <div className="form-field">
              <label htmlFor={`manual-model-dimension-${providerPublicId}`}>
                Embedding dimension
              </label>
              <input
                id={`manual-model-dimension-${providerPublicId}`}
                type="number"
                min="1"
                step="1"
                inputMode="numeric"
                aria-invalid={Boolean(form.formState.errors.embeddingDimension)}
                {...form.register("embeddingDimension", {
                  validate: (value) =>
                    (/^[1-9]\d*$/.test(value) &&
                      Number.isSafeInteger(Number(value))) ||
                    "Enter a positive whole-number dimension.",
                })}
              />
              {form.formState.errors.embeddingDimension ? (
                <p className="form-error" role="alert">
                  {form.formState.errors.embeddingDimension.message}
                </p>
              ) : null}
            </div>
          ) : null}

          {registrationFailed ? (
            <p className="provider-feedback" role="alert">
              The model could not be registered. Check the configuration and try
              again.
            </p>
          ) : null}
          <div className="provider-form-actions">
            <button
              className="primary-button"
              type="submit"
              disabled={!providerReady || registration.isPending}
            >
              {registration.isPending ? "Registering…" : "Register model"}
            </button>
            <button
              className="text-button"
              type="button"
              disabled={registration.isPending}
              onClick={resetAndClose}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
