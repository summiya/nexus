import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { NexusApiError } from "../../services/api/error";
import { requestLoginOtp } from "./api";

const EMAIL_MAX_LENGTH = 320;
const TEMPORARY_AUTH_ERROR =
  "Authentication is temporarily unavailable. Please try again.";

const emailSchema = z
  .string()
  .trim()
  .min(1, "Enter your email address.")
  .email("Enter a valid email address.")
  .max(EMAIL_MAX_LENGTH, "Email address is too long.");

interface EmailFormValues {
  email: string;
}

interface EmailLoginStepProps {
  initialEmail: string;
  onOtpRequested: (email: string) => void;
}

function validateEmail(value: string): true | string {
  const result = emailSchema.safeParse(value);
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

export function EmailLoginStep({
  initialEmail,
  onOtpRequested,
}: EmailLoginStepProps) {
  const [feedback, setFeedback] = useState<string | null>(null);
  const form = useForm<EmailFormValues>({
    defaultValues: { email: initialEmail },
  });

  const submit = form.handleSubmit(async ({ email }) => {
    const normalizedEmail = email.trim();
    setFeedback(null);
    try {
      await requestLoginOtp(normalizedEmail);
      onOtpRequested(normalizedEmail);
    } catch (error: unknown) {
      setFeedback(requestErrorMessage(error));
    }
  });

  return (
    <>
      <h1 id="login-title">Sign in</h1>
      <p>Enter your email address to receive a verification code.</p>

      <form className="auth-form" onSubmit={submit} noValidate>
        <div className="form-field">
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            maxLength={EMAIL_MAX_LENGTH}
            aria-invalid={Boolean(form.formState.errors.email)}
            aria-describedby={
              form.formState.errors.email ? "email-error" : undefined
            }
            {...form.register("email", { validate: validateEmail })}
          />
          {form.formState.errors.email ? (
            <p className="form-error" id="email-error" role="alert">
              {form.formState.errors.email.message}
            </p>
          ) : null}
        </div>

        {feedback ? (
          <p className="form-feedback error" role="alert">
            {feedback}
          </p>
        ) : null}

        <button
          className="primary-button"
          type="submit"
          disabled={form.formState.isSubmitting}
        >
          {form.formState.isSubmitting ? "Sending…" : "Continue"}
        </button>
      </form>
    </>
  );
}
