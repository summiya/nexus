import { useMemo, useState } from "react";

import { NexusApiError } from "../../services/api/error";
import {
  useProviderModelDiscoveryQuery,
  useRegisterModelsMutation,
} from "./queries";
import type { ConfiguredModel, ModelCandidate } from "./types";

const MAX_DISCOVERED_SELECTIONS = 50;

function discoveryError(error: unknown): string {
  if (error instanceof NexusApiError) {
    if (error.code === "RATE_LIMITED") {
      return "Too many discovery attempts. Try again later.";
    }
    if (error.code === "MODEL_DISCOVERY_UNSUPPORTED") {
      return "Automatic model discovery is not available for this provider.";
    }
  }
  return "Models could not be discovered. Try again.";
}

export function ModelDiscoveryPanel({
  providerPublicId,
  providerRevision,
  configuredModels,
  providerReady,
  providerReadinessMessage,
}: {
  providerPublicId: string;
  providerRevision: string | null;
  configuredModels: readonly ConfiguredModel[];
  providerReady: boolean;
  providerReadinessMessage: string;
}) {
  const discovery = useProviderModelDiscoveryQuery(
    providerPublicId,
    providerRevision,
  );
  const registration = useRegisterModelsMutation(providerPublicId);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [registrationFailed, setRegistrationFailed] = useState(false);
  const configuredNames = useMemo(
    () => new Set(configuredModels.map((model) => model.providerModelName)),
    [configuredModels],
  );
  const candidates = useMemo(
    () =>
      discovery.data?.filter(
        (candidate) => !configuredNames.has(candidate.providerModelName),
      ) ?? [],
    [configuredNames, discovery.data],
  );
  const candidateNames = useMemo(
    () =>
      new Set(
        candidates
          .filter(
            (candidate) =>
              candidate.modelType !== "embedding" ||
              candidate.embeddingDimension !== null,
          )
          .map((candidate) => candidate.providerModelName),
      ),
    [candidates],
  );
  const selectedCandidateNames = [...selected].filter((name) =>
    candidateNames.has(name),
  );

  function toggleCandidate(candidate: ModelCandidate) {
    setSelected((current) => {
      const next = new Set(
        [...current].filter((name) => candidateNames.has(name)),
      );
      if (next.has(candidate.providerModelName)) {
        next.delete(candidate.providerModelName);
      } else if (next.size < MAX_DISCOVERED_SELECTIONS) {
        next.add(candidate.providerModelName);
      }
      return next;
    });
  }

  async function registerSelected() {
    if (!providerReady) {
      return;
    }
    setRegistrationFailed(false);
    try {
      await registration.mutateAsync({
        registrationMode: "discovered",
        providerModelNames: selectedCandidateNames,
      });
      setSelected(new Set());
    } catch {
      setRegistrationFailed(true);
    }
  }

  return (
    <section className="model-registration-panel" aria-label="Discover models">
      {!providerReady ? (
        <p className="model-readiness-note">{providerReadinessMessage}</p>
      ) : null}
      <button
        className="text-button"
        type="button"
        disabled={
          !providerReady || discovery.isFetching || registration.isPending
        }
        onClick={() => {
          setRegistrationFailed(false);
          setSelected(new Set());
          void discovery.refetch();
        }}
      >
        {discovery.isFetching ? "Discovering…" : "Discover models"}
      </button>

      {discovery.isError ? (
        <div className="model-registration-error" role="alert">
          <p>{discoveryError(discovery.error)}</p>
          <button
            className="text-button"
            type="button"
            disabled={!providerReady || discovery.isFetching}
            onClick={() => void discovery.refetch()}
          >
            Retry
          </button>
        </div>
      ) : null}

      {discovery.isSuccess ? (
        candidates.length === 0 ? (
          <p>No additional models are available to register.</p>
        ) : (
          <div className="model-candidate-list">
            {candidates.map((candidate) => {
              const missingDimension =
                candidate.modelType === "embedding" &&
                candidate.embeddingDimension === null;
              return (
                <label
                  className="model-candidate"
                  key={candidate.providerModelName}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(candidate.providerModelName)}
                    disabled={
                      missingDimension ||
                      registration.isPending ||
                      (!selected.has(candidate.providerModelName) &&
                        selected.size >= MAX_DISCOVERED_SELECTIONS)
                    }
                    onChange={() => toggleCandidate(candidate)}
                  />
                  <span>
                    <strong>{candidate.displayName}</strong>
                    <small>
                      {candidate.modelType}
                      {candidate.capabilities.length > 0
                        ? ` · ${candidate.capabilities.join(" · ")}`
                        : ""}
                      {candidate.embeddingDimension !== null
                        ? ` · ${candidate.embeddingDimension} dimensions`
                        : ""}
                    </small>
                    {missingDimension ? (
                      <small>
                        Registration requires a known embedding dimension.
                      </small>
                    ) : null}
                  </span>
                </label>
              );
            })}
            {registrationFailed ? (
              <p className="provider-feedback" role="alert">
                The selected models could not be registered. Refresh discovery
                and try again.
              </p>
            ) : null}
            <button
              className="primary-button model-register-button"
              type="button"
              disabled={
                !providerReady ||
                selectedCandidateNames.length === 0 ||
                registration.isPending
              }
              onClick={() => void registerSelected()}
            >
              {registration.isPending
                ? "Registering…"
                : `Register selected (${selectedCandidateNames.length})`}
            </button>
          </div>
        )
      ) : null}
    </section>
  );
}
