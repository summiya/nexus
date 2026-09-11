import { useEffect } from 'react';

import { useNexusApp } from '../context/AppContext';
import { getHealth } from '../services/api/client';

export function HomePage() {
  const { isLoading, error, setError, setIsLoading } = useNexusApp();

  useEffect(() => {
    let isMounted = true;

    const loadHealth = async () => {
      setIsLoading(true);
      setError(null);

      try {
        await getHealth();
      } catch (loadError) {
        if (isMounted) {
          const message =
            loadError instanceof Error
              ? loadError.message
              : 'The backend health endpoint is unavailable.';
          setError(message);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    void loadHealth();

    return () => {
      isMounted = false;
    };
  }, [setError, setIsLoading]);

  return (
    <section className="hero-card">
      <p className="eyebrow">NEXUS</p>
      <h1>Application foundation</h1>
      <p>
        React, TypeScript, routing, state management, and the API client foundation are in place.
      </p>

      <div className="metrics-grid">
        <div className="surface-card">
          <span className="label">Status</span>
          <strong>{isLoading ? 'Loading' : 'Ready'}</strong>
        </div>
        <div className="surface-card">
          <span className="label">API</span>
          <strong>{error ? 'Unhealthy' : 'Healthy'}</strong>
        </div>
      </div>

      {error ? (
        <p className="status-note error">{error}</p>
      ) : (
        <p className="status-note">The foundation is ready for future workflow and product work.</p>
      )}
    </section>
  );
}
