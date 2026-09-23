import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { AuthStatusView } from "./AuthStatusView";
import { EmailLoginStep } from "./EmailLoginStep";
import { OtpVerificationStep } from "./OtpVerificationStep";
import { establishSession } from "./session";
import { useAuthStore } from "./store";
import type { SessionTokens } from "./types";

function intendedDestination(state: unknown): string {
  if (
    !state ||
    typeof state !== "object" ||
    Array.isArray(state) ||
    !Object.prototype.hasOwnProperty.call(state, "from")
  ) {
    return "/";
  }

  const from = (state as { from?: unknown }).from;
  if (
    typeof from !== "string" ||
    !from.startsWith("/") ||
    from.startsWith("//") ||
    from.includes("\\")
  ) {
    return "/";
  }

  try {
    const destination = new URL(from, window.location.origin);
    const pathname = destination.pathname.replace(/\/+$/, "") || "/";
    if (
      destination.origin !== window.location.origin ||
      pathname.toLowerCase() === "/login"
    ) {
      return "/";
    }
  } catch {
    return "/";
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
    <main className="login-page">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="login-brand" aria-hidden="true">
          N
        </div>
        <p className="eyebrow">NEXUS</p>

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
    </main>
  );
}
