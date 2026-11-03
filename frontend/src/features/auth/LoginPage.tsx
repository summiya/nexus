import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { AuthStatusView } from "./AuthStatusView";
import { EmailLoginStep } from "./EmailLoginStep";
import { OtpVerificationStep } from "./OtpVerificationStep";
import { establishSession } from "./session";
import { useAuthStore } from "./store";
import type { SessionTokens } from "./types";

import "../../styles/nexus-experience.css";

const DEFAULT_AUTHENTICATED_DESTINATION = "/conversations";

function intendedDestination(state: unknown): string {
  if (
    !state ||
    typeof state !== "object" ||
    Array.isArray(state) ||
    !Object.prototype.hasOwnProperty.call(state, "from")
  ) {
    return DEFAULT_AUTHENTICATED_DESTINATION;
  }

  const from = (state as { from?: unknown }).from;
  if (
    typeof from !== "string" ||
    !from.startsWith("/") ||
    from.startsWith("//") ||
    from.includes("\\")
  ) {
    return DEFAULT_AUTHENTICATED_DESTINATION;
  }

  try {
    const destination = new URL(from, window.location.origin);
    const pathname = destination.pathname.replace(/\/+$/, "") || "/";
    if (
      destination.origin !== window.location.origin ||
      pathname.toLowerCase() === "/login"
    ) {
      return DEFAULT_AUTHENTICATED_DESTINATION;
    }
  } catch {
    return DEFAULT_AUTHENTICATED_DESTINATION;
  }

  return from;
}

export function LoginPage() {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();
  const navigate = useNavigate();
  const destination = intendedDestination(location.state);
  const [emailDraft, setEmailDraft] = useState("");
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

  if (status === "initializing" || status === "unavailable") {
    return <AuthStatusView status={status} />;
  }

  if (status === "authenticated") {
    return <Navigate to={destination} replace />;
  }

  function otpRequested(email: string): void {
    setEmailDraft(email);
    setSubmittedEmail(email);
  }

  function completeLogin(tokens: SessionTokens): void {
    establishSession(tokens);
    navigate(destination, { replace: true });
  }

  return (
    <main className="login-page nexus-auth-page">
      <aside className="nx-auth-aside">
        <Link to="/" className="nx-brand" aria-label="NEXUS homepage">
          <span className="nx-brand-mark" aria-hidden="true">
            N
          </span>
          <span className="nx-brand-text">
            <strong>NEXUS</strong>
            <small>AI WORKSPACE</small>
          </span>
        </Link>
        <div className="nx-auth-aside-content">
          <span>YOUR IDEAS, CONNECTED</span>
          <h2>
            One workspace.
            <br />
            <span>Limitless ways to think.</span>
          </h2>
          <p>
            Bring your AI models, conversations and files into one place.
            NEXUS starts with great conversations and grows with your work.
          </p>
          <div className="nx-auth-points">
            <span>✧ Model choice</span>
            <span>◈ File workspace</span>
            <span>◇ Organization-aware access</span>
          </div>
        </div>
        <span className="nx-auth-aside-footer">
          NEXUS · Built for a more intelligent way to work
        </span>
      </aside>
      <div className="nx-auth-right">
        <div className="nx-auth-content">
          <section className="auth-card" aria-labelledby="login-title">
            <div className="nx-auth-card-intro">
              <span aria-hidden="true">✧</span>
              <span>SECURE PASSWORDLESS ACCESS</span>
            </div>
            {submittedEmail ? (
              <OtpVerificationStep
                email={submittedEmail}
                onVerified={completeLogin}
                onChangeEmail={() => setSubmittedEmail(null)}
              />
            ) : (
              <EmailLoginStep
                initialEmail={emailDraft}
                onOtpRequested={otpRequested}
              />
            )}
          </section>
          <p className="nx-auth-below">
            Want to learn more? <Link to="/">Explore the NEXUS platform</Link>
          </p>
        </div>
      </div>
    </main>
  );
}
