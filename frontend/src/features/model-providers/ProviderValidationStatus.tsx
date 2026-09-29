import type { ProviderValidationStatus as ValidationStatus } from "./types";

const labels: Record<ValidationStatus, string> = {
  unvalidated: "Not validated",
  valid: "Valid",
  invalid_credentials: "Invalid credentials",
  unreachable: "Provider unreachable",
  unsupported_configuration: "Unsupported configuration",
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ProviderValidationStatus({
  status,
  lastValidatedAt,
}: {
  status: ValidationStatus;
  lastValidatedAt: string | null;
}) {
  return (
    <div>
      <dt>Validation</dt>
      <dd>{labels[status]}</dd>
      {lastValidatedAt ? (
        <>
          <dt>Last checked</dt>
          <dd>
            <time dateTime={lastValidatedAt}>
              {formatDate(lastValidatedAt)}
            </time>
          </dd>
        </>
      ) : null}
    </div>
  );
}
