import { useState } from "react";
import { useForm } from "react-hook-form";

const MAX_CREDENTIAL_BYTES = 16 * 1024;

interface CredentialValues {
  credential: string;
}

interface ProviderCredentialFormProps {
  providerPublicId: string;
  replacing: boolean;
  onSubmit: (credential: string) => Promise<boolean>;
  onCancel: () => void;
}

function validateCredential(value: string): true | string {
  if (value.length === 0) {
    return "Enter the provider credential.";
  }
  return new TextEncoder().encode(value).length <= MAX_CREDENTIAL_BYTES
    ? true
    : "Provider credential is too long.";
}

export function ProviderCredentialForm({
  providerPublicId,
  replacing,
  onSubmit,
  onCancel,
}: ProviderCredentialFormProps) {
  const [revealed, setRevealed] = useState(false);
  const form = useForm<CredentialValues>({ defaultValues: { credential: "" } });

  const submit = form.handleSubmit(async ({ credential }) => {
    if (await onSubmit(credential)) {
      form.reset({ credential: "" });
      setRevealed(false);
    }
  });

  function cancel() {
    form.reset({ credential: "" });
    setRevealed(false);
    onCancel();
  }

  return (
    <form className="provider-form" onSubmit={submit} noValidate>
      <div className="form-field">
        <label htmlFor={`provider-credential-${providerPublicId}`}>
          Provider credential
        </label>
        <input
          id={`provider-credential-${providerPublicId}`}
          type={revealed ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={Boolean(form.formState.errors.credential)}
          {...form.register("credential", { validate: validateCredential })}
        />
        {form.formState.errors.credential ? (
          <p className="form-error" role="alert">
            {form.formState.errors.credential.message}
          </p>
        ) : null}
      </div>
      <label className="provider-reveal-control">
        <input
          type="checkbox"
          checked={revealed}
          disabled={form.formState.isSubmitting}
          onChange={(event) => setRevealed(event.target.checked)}
        />
        Show the credential being entered
      </label>
      <div className="provider-form-actions">
        <button
          className="primary-button"
          type="submit"
          disabled={form.formState.isSubmitting}
        >
          {form.formState.isSubmitting
            ? "Saving…"
            : replacing
              ? "Replace credential"
              : "Add credential"}
        </button>
        <button
          className="text-button"
          type="button"
          disabled={form.formState.isSubmitting}
          onClick={cancel}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
