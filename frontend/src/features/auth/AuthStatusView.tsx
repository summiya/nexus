import { initializeSession } from "./session";
import type { AuthStatus } from "./types";

export function AuthStatusView({ status }: { status: AuthStatus }) {
  if (status === "unavailable") {
    return (
      <main className="auth-status" aria-labelledby="auth-status-title">
        <div className="auth-card auth-status-card">
          <p className="eyebrow">NEXUS</p>
          <h1 id="auth-status-title">Session temporarily unavailable</h1>
          <p>
            Nexus could not restore your session. Your sign-in has been kept
            safe, and you can try again.
          </p>
          <button
            className="primary-button"
            type="button"
            onClick={() => void initializeSession().catch(() => undefined)}
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="auth-status" aria-live="polite">
      <div className="auth-card auth-status-card">
        <p className="eyebrow">NEXUS</p>
        <h1>Restoring your session</h1>
        <p>Please wait while Nexus securely restores your session.</p>
      </div>
    </main>
  );
}
