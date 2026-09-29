import { useForm } from "react-hook-form";

import type {
  ConfiguredProvider,
  CreateProviderInput,
  ProviderCatalogItem,
  ProviderSettingName,
  UpdateProviderInput,
} from "./types";

const DISPLAY_NAME_MAX_LENGTH = 200;
const API_VERSION_MAX_LENGTH = 64;
const URL_MAX_LENGTH = 2048;

interface ProviderConfigurationValues {
  displayName: string;
  settings: Record<string, string>;
}

interface ProviderConfigurationFormProps {
  catalogItem: ProviderCatalogItem;
  provider?: ConfiguredProvider;
  onSubmit: (input: CreateProviderInput | UpdateProviderInput) => Promise<void>;
  onCancel: () => void;
}

const settingLabels: Record<ProviderSettingName, string> = {
  endpoint: "Endpoint",
  api_version: "API version",
  base_url: "Base URL",
};

function isUrlSetting(name: ProviderSettingName): boolean {
  return name === "endpoint" || name === "base_url";
}

function validateSetting(
  name: ProviderSettingName,
  value: string,
): true | string {
  const normalized = value.trim();
  if (!normalized) {
    return `${settingLabels[name]} is required.`;
  }
  if (name === "api_version") {
    return normalized.length <= API_VERSION_MAX_LENGTH
      ? true
      : "API version is too long.";
  }
  if (normalized.length > URL_MAX_LENGTH) {
    return `${settingLabels[name]} is too long.`;
  }
  try {
    return new URL(normalized).protocol === "https:"
      ? true
      : `${settingLabels[name]} must use HTTPS.`;
  } catch {
    return `${settingLabels[name]} must be a valid URL.`;
  }
}

function normalizedSettings(
  names: readonly ProviderSettingName[],
  values: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    names.map((name) => [name, values[name]?.trim() ?? ""]),
  );
}

export function ProviderConfigurationForm({
  catalogItem,
  provider,
  onSubmit,
  onCancel,
}: ProviderConfigurationFormProps) {
  const initialSettings = Object.fromEntries(
    catalogItem.requiredSettings.map((name) => [
      name,
      provider?.settings[name] ?? "",
    ]),
  );
  const form = useForm<ProviderConfigurationValues>({
    defaultValues: {
      displayName: provider?.displayName ?? catalogItem.displayName,
      settings: initialSettings,
    },
  });
  const watchedSettings = form.watch("settings");
  const urlChanged =
    provider?.credentialConfigured === true &&
    catalogItem.requiredSettings.some(
      (name) =>
        isUrlSetting(name) &&
        (watchedSettings[name]?.trim() ?? "") !==
          (provider.settings[name] ?? ""),
    );

  const submit = form.handleSubmit(async (values) => {
    const displayName = values.displayName.trim();
    const settings = normalizedSettings(
      catalogItem.requiredSettings,
      values.settings,
    );
    if (provider === undefined) {
      await onSubmit({
        providerType: catalogItem.providerType,
        displayName,
        settings,
      });
      return;
    }

    const update: UpdateProviderInput = {};
    if (displayName !== provider.displayName) {
      update.displayName = displayName;
    }
    if (
      catalogItem.requiredSettings.some(
        (name) => settings[name] !== (provider.settings[name] ?? ""),
      )
    ) {
      update.settings = settings;
    }
    if (update.displayName !== undefined || update.settings !== undefined) {
      await onSubmit(update);
    }
  });

  return (
    <form className="provider-form" onSubmit={submit} noValidate>
      <div className="form-field">
        <label
          htmlFor={`provider-name-${provider?.publicId ?? catalogItem.providerType}`}
        >
          Display name
        </label>
        <input
          id={`provider-name-${provider?.publicId ?? catalogItem.providerType}`}
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

      {catalogItem.requiredSettings.map((name) => {
        const error = form.formState.errors.settings?.[name];
        return (
          <div className="form-field" key={name}>
            <label
              htmlFor={`provider-setting-${provider?.publicId ?? catalogItem.providerType}-${name}`}
            >
              {settingLabels[name]}
            </label>
            <input
              id={`provider-setting-${provider?.publicId ?? catalogItem.providerType}-${name}`}
              type={isUrlSetting(name) ? "url" : "text"}
              maxLength={
                name === "api_version" ? API_VERSION_MAX_LENGTH : URL_MAX_LENGTH
              }
              aria-invalid={Boolean(error)}
              {...form.register(`settings.${name}`, {
                validate: (value) => validateSetting(name, value),
              })}
            />
            {error ? (
              <p className="form-error" role="alert">
                {error.message}
              </p>
            ) : null}
          </div>
        );
      })}

      {urlChanged ? (
        <p className="provider-warning" role="status">
          Changing this provider URL removes its stored credential. You will
          need to enter the credential again.
        </p>
      ) : null}

      <div className="provider-form-actions">
        <button
          className="primary-button"
          type="submit"
          disabled={
            form.formState.isSubmitting ||
            (provider !== undefined && !form.formState.isDirty)
          }
        >
          {form.formState.isSubmitting
            ? "Saving…"
            : provider
              ? "Save"
              : "Configure"}
        </button>
        <button
          className="text-button"
          type="button"
          disabled={form.formState.isSubmitting}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
