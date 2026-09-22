import { z } from "zod";

import { apiRequest } from "../../services/api/client";
import type { SessionTokens } from "./types";

const loginOtpResponseSchema = z
  .object({
    status: z.literal("accepted"),
  })
  .strict();

const tokenFields = {
  access_token: z.string().min(1),
  refresh_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
};

const loginVerificationResponseSchema = z
  .object({
    status: z.literal("completed"),
    ...tokenFields,
  })
  .strict();

const refreshSessionResponseSchema = z.object(tokenFields).strict();

function invalidAuthenticationResponse(): Error {
  return new Error("The authentication service returned an invalid response.");
}

function parseResponse<T>(schema: z.ZodType<T>, response: unknown): T {
  const result = schema.safeParse(response);
  if (!result.success) {
    throw invalidAuthenticationResponse();
  }

  return result.data;
}

function toSessionTokens(response: {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}): SessionTokens {
  return {
    accessToken: response.access_token,
    refreshToken: response.refresh_token,
    tokenType: response.token_type,
    expiresIn: response.expires_in,
  };
}

export async function requestLoginOtp(email: string): Promise<void> {
  const response = await apiRequest<unknown>("/auth/login", {
    method: "POST",
    authentication: "none",
    body: { email },
  });
  parseResponse(loginOtpResponseSchema, response);
}

export async function verifyLoginOtp(
  email: string,
  otp: string,
): Promise<SessionTokens> {
  const response = await apiRequest<unknown>("/auth/login/verify", {
    method: "POST",
    authentication: "none",
    body: { email, otp },
  });

  return toSessionTokens(
    parseResponse(loginVerificationResponseSchema, response),
  );
}

export async function refreshSession(
  refreshToken: string,
): Promise<SessionTokens> {
  const response = await apiRequest<unknown>("/auth/refresh", {
    method: "POST",
    authentication: "none",
    body: { refresh_token: refreshToken },
  });

  return toSessionTokens(parseResponse(refreshSessionResponseSchema, response));
}
