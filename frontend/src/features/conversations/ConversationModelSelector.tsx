import type { SelectableChatModel } from "./types";

interface ConversationModelSelectorProps {
  models: readonly SelectableChatModel[];
  defaultModelPublicId: string | null;
  explicitModelPublicId: string | null;
  isLoading: boolean;
  isError: boolean;
  disabled: boolean;
  onChange: (modelPublicId: string | null) => void;
  onRetry: () => void;
}

export function ConversationModelSelector({
  models,
  defaultModelPublicId,
  explicitModelPublicId,
  isLoading,
  isError,
  disabled,
  onChange,
  onRetry,
}: ConversationModelSelectorProps) {
  const selectedValue = explicitModelPublicId ?? defaultModelPublicId ?? "";
  const unavailable = isLoading || isError || models.length === 0;
  const providerGroups = new Map<
    string,
    { label: string; models: SelectableChatModel[] }
  >();
  for (const model of models) {
    const key = `${model.providerType}:${model.providerDisplayName}`;
    const group = providerGroups.get(key);
    if (group) {
      group.models.push(model);
    } else {
      providerGroups.set(key, {
        label: model.providerDisplayName,
        models: [model],
      });
    }
  }

  return (
    <div className="conversation-model-selector">
      <label htmlFor="conversation-model">Model</label>
      <select
        className="conversation-model-select"
        id="conversation-model"
        value={selectedValue}
        disabled={disabled || unavailable}
        onChange={(event) => {
          const value = event.target.value;
          onChange(
            value === "" || value === defaultModelPublicId ? null : value,
          );
        }}
      >
        {defaultModelPublicId === null ? (
          <option value="">Select a model</option>
        ) : null}
        {[...providerGroups.entries()].map(([key, group]) => (
          <optgroup key={key} label={group.label}>
            {group.models.map((model) => (
              <option key={model.publicId} value={model.publicId}>
                {model.displayName}
                {model.publicId === defaultModelPublicId ? " — Default" : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {isLoading ? <p role="status">Loading models…</p> : null}
      {isError ? (
        <div className="conversation-model-state" role="alert">
          <p>Chat models are temporarily unavailable.</p>
          <button className="text-button" type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : null}
      {!isLoading && !isError && models.length === 0 ? (
        <p className="conversation-model-state">
          No chat model is available. Ask an administrator to configure one.
        </p>
      ) : null}
      {!isLoading &&
      !isError &&
      models.length > 0 &&
      defaultModelPublicId === null &&
      explicitModelPublicId === null ? (
        <p className="conversation-model-state">
          Select a model before sending a message.
        </p>
      ) : null}
    </div>
  );
}
