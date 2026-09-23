import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import { NexusApiError } from "../../services/api/error";
import { requestLoginOtp, verifyLoginOtp } from "./api";
import { SessionRestoreState } from "./AuthGate";
import { establishSession } from "./session";
import { useAuthStore } from "./store";

const EMAIL_MAX_LENGTH = 320;
const OTP_MIN_LENGTH = 6;
const OTP_MAX_LENGTH = 10;
const GENERIC_OTP_SENT_MESSAGE =
  "If an account exists for this email, a verification code has been sent.";
const TEMPORARY_AUTH_ERROR =
  "Authentication is temporarily unavailable. Please try again.";

const emailSchema = z
  .string()
  .trim()
  .min(1, "Enter your email address.")
  .email("Enter a valid email address.")
  .max(EMAIL_MAX_LENGTH, "Email address is too long.");

const otpSchema = z
  .string()
  .min(1, "Enter the verification code.")
  .regex(/^\d+$/, "Verification code must contain digits only.")
  .min(OTP_MIN_LENGTH, "Verification code is too short.")
  .max(OTP_MAX_LENGTH, "Verification code is too long.");

interface EmailFormValues {
  email: string;
}

interface OtpFormValues {
  otp: string;
}

interface Feedback {
  kind: "error" | "success";
  message: string;
}

function validateField(
  schema: z.ZodType<string>,
  value: string,
): true | string {
  const result = schema.safeParse(value);
  return result.success
    ? true
    : (result.error.issues[0]?.message ?? "This value is invalid.");
}

function requestErrorMessage(error: unknown): string {
  if (error instanceof NexusApiError && error.code === "RATE_LIMITED") {
    return "Too many attempts. Please try again later.";
  }

  return TEMPORARY_AUTH_ERROR;
}

function verificationErrorMessage(error: unknown): string {
  if (error instanceof NexusApiError) {
    if (error.code === "RATE_LIMITED") {
      return "Too many attempts. Please try again later.";
    }
    if (error.code === "SERVICE_UNAVAILABLE" || error.status >= 500) {
      return TEMPORARY_AUTH_ERROR;
    }
    if (error.code === "UNAUTHORIZED" || error.status === 401) {
      return "The verification code is invalid or expired.";
    }
  }

  return TEMPORARY_AUTH_ERROR;
}

function intendedDestination(state: unknown): string {
  if (!state || typeof state !== "object" || !("from" in state)) {
    return "/";
  }

  const from = state.from;
  return typeof from === "string" &&
    from.startsWith("/") &&
    !from.startsWith("//")
    ? from
    : "/";
}

export function LoginPage() {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();
  const navigate = useNavigate();
  const destination = intendedDestination(location.state);
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);
  const [emailFeedback, setEmailFeedback] = useState<Feedback | null>(null);
  const [otpFeedback, setOtpFeedback] = useState<Feedback | null>(null);
  const [isResending, setIsResending] = useState(false);
  const emailForm = useForm<EmailFormValues>({
    defaultValues: { email: "" },
  });
  const otpForm = useForm<OtpFormValues>({
    defaultValues: { otp: "" },
  });

  if (status === "initializing" || status === "unavailable") {
    return <SessionRestoreState status={status} />;
  }

  if (status === "authenticated") {
    return <Navigate to={destination} replace />;
  }

  const submitEmail = emailForm.handleSubmit(async ({ email }) => {
    const normalizedEmail = email.trim();
    setEmailFeedback(null);
    try {
      await requestLoginOtp(normalizedEmail);
      setSubmittedEmail(normalizedEmail);
      otpForm.reset({ otp: "" });
      setOtpFeedback({ kind: "success", message: GENERIC_OTP_SENT_MESSAGE });
    } catch (error: unknown) {
      setEmailFeedback({ kind: "error", message: requestErrorMessage(error) });
    }
  });

  const submitOtp = otpForm.handleSubmit(async ({ otp }) => {
    if (!submittedEmail) {
      return;
    }

    setOtpFeedback(null);
    try {
      const tokens = await verifyLoginOtp(submittedEmail, otp);
      establishSession(tokens);
      navigate(destination, { replace: true });
    } catch (error: unknown) {
      setOtpFeedback({
        kind: "error",
        message: verificationErrorMessage(error),
      });
    }
  });

  async function resendOtp(): Promise<void> {
    if (!submittedEmail || isResending) {
      return;
    }

    setIsResending(true);
    setOtpFeedback(null);
    try {
      await requestLoginOtp(submittedEmail);
      setOtpFeedback({ kind: "success", message: GENERIC_OTP_SENT_MESSAGE });
    } catch (error: unknown) {
      setOtpFeedback({ kind: "error", message: requestErrorMessage(error) });
    } finally {
      setIsResending(false);
    }
  }

  function changeEmail(): void {
    otpForm.reset({ otp: "" });
    setOtpFeedback(null);
    setSubmittedEmail(null);
  }

  return (
    <main className="login-page">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="login-brand" aria-hidden="true">
          N
        </div>
        <p className="eyebrow">NEXUS</p>

        {submittedEmail ? (
          <>
            <h1 id="login-title">Check your email</h1>
            <p>
              Code sent for <strong>{submittedEmail}</strong>
            </p>

            <form className="auth-form" onSubmit={submitOtp} noValidate>
              <div className="form-field">
                <label htmlFor="otp">Verification code</label>
                <input
                  key="otp"
                  id="otp"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete="one-time-code"
                  autoFocus
                  maxLength={OTP_MAX_LENGTH}
                  aria-invalid={Boolean(otpForm.formState.errors.otp)}
                  aria-describedby={
                    otpForm.formState.errors.otp ? "otp-error" : undefined
                  }
                  {...otpForm.register("otp", {
                    validate: (value) => validateField(otpSchema, value),
                  })}
                />
                {otpForm.formState.errors.otp ? (
                  <p className="form-error" id="otp-error" role="alert">
                    {otpForm.formState.errors.otp.message}
                  </p>
                ) : null}
              </div>

              {otpFeedback ? (
                <p
                  className={`form-feedback ${otpFeedback.kind}`}
                  role={otpFeedback.kind === "error" ? "alert" : "status"}
                  aria-live="polite"
                >
                  {otpFeedback.message}
                </p>
              ) : null}

              <button
                className="primary-button"
                type="submit"
                disabled={otpForm.formState.isSubmitting || isResending}
              >
                {otpForm.formState.isSubmitting ? "Verifying…" : "Verify"}
              </button>
            </form>

            <div className="auth-actions">
              <button
                className="text-button"
                type="button"
                disabled={otpForm.formState.isSubmitting || isResending}
                onClick={() => void resendOtp()}
              >
                {isResending ? "Sending…" : "Resend code"}
              </button>
              <button
                className="text-button"
                type="button"
                disabled={otpForm.formState.isSubmitting || isResending}
                onClick={changeEmail}
              >
                Change email
              </button>
            </div>
          </>
        ) : (
          <>
            <h1 id="login-title">Sign in</h1>
            <p>Enter your email address to receive a verification code.</p>

            <form className="auth-form" onSubmit={submitEmail} noValidate>
              <div className="form-field">
                <label htmlFor="email">Email address</label>
                <input
                  key="email"
                  id="email"
                  type="email"
                  autoComplete="email"
                  autoFocus
                  maxLength={EMAIL_MAX_LENGTH}
                  aria-invalid={Boolean(emailForm.formState.errors.email)}
                  aria-describedby={
                    emailForm.formState.errors.email ? "email-error" : undefined
                  }
                  {...emailForm.register("email", {
                    validate: (value) => validateField(emailSchema, value),
                  })}
                />
                {emailForm.formState.errors.email ? (
                  <p className="form-error" id="email-error" role="alert">
                    {emailForm.formState.errors.email.message}
                  </p>
                ) : null}
              </div>

              {emailFeedback ? (
                <p className="form-feedback error" role="alert">
                  {emailFeedback.message}
                </p>
              ) : null}

              <button
                className="primary-button"
                type="submit"
                disabled={emailForm.formState.isSubmitting}
              >
                {emailForm.formState.isSubmitting ? "Sending…" : "Continue"}
              </button>
            </form>
          </>
        )}
      </section>
    </main>
  );
}
