import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { NexusApiError } from "../../services/api/error";
import { requestLoginOtp, verifyLoginOtp } from "./api";
import type { SessionTokens } from "./types";

const OTP_MIN_LENGTH = 6;
const OTP_MAX_LENGTH = 10;
const GENERIC_OTP_SENT_MESSAGE =
  "If an account exists for this email, a verification code has been sent.";
const TEMPORARY_AUTH_ERROR =
  "Authentication is temporarily unavailable. Please try again.";

const otpSchema = z
  .string()
  .min(1, "Enter the verification code.")
  .regex(/^\d+$/, "Verification code must contain digits only.")
  .min(OTP_MIN_LENGTH, "Verification code is too short.")
  .max(OTP_MAX_LENGTH, "Verification code is too long.");

interface OtpFormValues {
  otp: string;
}

interface Feedback {
  kind: "error" | "success";
  message: string;
}

interface OtpVerificationStepProps {
  email: string;
  onVerified: (tokens: SessionTokens) => void;
  onChangeEmail: () => void;
}

function validateOtp(value: string): true | string {
  const result = otpSchema.safeParse(value);
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

export function OtpVerificationStep({
  email,
  onVerified,
  onChangeEmail,
}: OtpVerificationStepProps) {
  const [feedback, setFeedback] = useState<Feedback | null>({
    kind: "success",
    message: GENERIC_OTP_SENT_MESSAGE,
  });
  const [isResending, setIsResending] = useState(false);
  const form = useForm<OtpFormValues>({
    defaultValues: { otp: "" },
  });

  const submit = form.handleSubmit(async ({ otp }) => {
    setFeedback(null);
    try {
      const tokens = await verifyLoginOtp(email, otp);
      onVerified(tokens);
    } catch (error: unknown) {
      setFeedback({
        kind: "error",
        message: verificationErrorMessage(error),
      });
    }
  });

  async function resendOtp(): Promise<void> {
    if (isResending) {
      return;
    }

    setIsResending(true);
    setFeedback(null);
    try {
      await requestLoginOtp(email);
      setFeedback({ kind: "success", message: GENERIC_OTP_SENT_MESSAGE });
    } catch (error: unknown) {
      setFeedback({ kind: "error", message: requestErrorMessage(error) });
    } finally {
      setIsResending(false);
    }
  }

  return (
    <>
      <h1 id="login-title">Check your email</h1>
      <p>
        Code sent for <strong>{email}</strong>
      </p>

      <form className="auth-form" onSubmit={submit} noValidate>
        <div className="form-field">
          <label htmlFor="otp">Verification code</label>
          <input
            id="otp"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="one-time-code"
            autoFocus
            maxLength={OTP_MAX_LENGTH}
            aria-invalid={Boolean(form.formState.errors.otp)}
            aria-describedby={
              form.formState.errors.otp ? "otp-error" : undefined
            }
            {...form.register("otp", { validate: validateOtp })}
          />
          {form.formState.errors.otp ? (
            <p className="form-error" id="otp-error" role="alert">
              {form.formState.errors.otp.message}
            </p>
          ) : null}
        </div>

        {feedback ? (
          <p
            className={`form-feedback ${feedback.kind}`}
            role={feedback.kind === "error" ? "alert" : "status"}
            aria-live="polite"
          >
            {feedback.message}
          </p>
        ) : null}

        <button
          className="primary-button"
          type="submit"
          disabled={form.formState.isSubmitting || isResending}
        >
          {form.formState.isSubmitting ? "Verifying…" : "Verify"}
        </button>
      </form>

      <div className="auth-actions">
        <button
          className="text-button"
          type="button"
          disabled={form.formState.isSubmitting || isResending}
          onClick={() => void resendOtp()}
        >
          {isResending ? "Sending…" : "Resend code"}
        </button>
        <button
          className="text-button"
          type="button"
          disabled={form.formState.isSubmitting || isResending}
          onClick={onChangeEmail}
        >
          Change email
        </button>
      </div>
    </>
  );
}
