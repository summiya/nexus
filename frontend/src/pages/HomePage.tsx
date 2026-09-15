import { useQuery } from "@tanstack/react-query";

import { getHealth } from "../services/api/client";

export function HomePage() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  return (
    <section className="hero-card">
      <p className="eyebrow">NEXUS</p>
      <h1>Application foundation</h1>
      <p>
        React, TypeScript, routing, server-state management, and the API client
        foundation are in place.
      </p>

      <div className="metrics-grid">
        <div className="surface-card">
          <span className="label">Status</span>
          <strong>{health.isPending ? "Loading" : "Ready"}</strong>
        </div>
        <div className="surface-card">
          <span className="label">API</span>
          <strong>{health.isError ? "Unhealthy" : "Healthy"}</strong>
        </div>
      </div>

      {health.isError ? (
        <p className="status-note error" role="alert">
          {health.error instanceof Error
            ? health.error.message
            : "The backend health endpoint is unavailable."}
        </p>
      ) : (
        <p className="status-note">
          The foundation is ready for future workflow and product work.
        </p>
      )}
    </section>
  );
}
