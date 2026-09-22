import { env } from "../../config/env";
import { toNexusApiError } from "./error";

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  authentication?: "none" | "required";
  body?: BodyInit | Record<string, unknown> | null;
};

interface ApiAuthenticationBridge {
  getAccessToken(): string | null;
  refreshAccessToken(expiredAccessToken: string): Promise<void>;
}

interface ApiResponse {
  response: Response;
  accessToken: string | null;
}

let authenticationBridge: ApiAuthenticationBridge | undefined;

export function configureApiAuthentication(
  bridge: ApiAuthenticationBridge | undefined,
): void {
  authenticationBridge = bridge;
}

function requestBody(body: ApiRequestOptions["body"]): BodyInit | null {
  const isFormData =
    typeof FormData !== "undefined" && body instanceof FormData;

  if (body && typeof body !== "string" && !isFormData) {
    return JSON.stringify(body);
  }

  return body ?? null;
}

async function sendRequest(
  path: string,
  options: ApiRequestOptions,
): Promise<ApiResponse> {
  const {
    authentication = "required",
    body,
    headers,
    ...requestOptions
  } = options;
  const requestHeaders = new Headers(headers);
  const isFormData =
    typeof FormData !== "undefined" && body instanceof FormData;

  if (body && !isFormData && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const hasExplicitAuthorization = requestHeaders.has("Authorization");
  const accessToken =
    authentication === "required" && !hasExplicitAuthorization
      ? (authenticationBridge?.getAccessToken() ?? null)
      : null;
  if (accessToken) {
    requestHeaders.set("Authorization", `Bearer ${accessToken}`);
  }

  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    ...requestOptions,
    body: requestBody(body),
    headers: requestHeaders,
  });

  return { response, accessToken };
}

async function readSuccessfulResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const initial = await sendRequest(path, options);
  if (initial.response.ok) {
    return readSuccessfulResponse<T>(initial.response);
  }

  const initialError = await toNexusApiError(initial.response);
  if (
    options.authentication !== "none" &&
    initialError.code === "ACCESS_TOKEN_EXPIRED" &&
    initial.accessToken !== null &&
    authenticationBridge
  ) {
    await authenticationBridge.refreshAccessToken(initial.accessToken);

    const retry = await sendRequest(path, options);
    if (!retry.response.ok) {
      throw await toNexusApiError(retry.response);
    }

    return readSuccessfulResponse<T>(retry.response);
  }

  throw initialError;
}

export function getHealth() {
  return apiRequest<{ status: string }>("/health", {
    authentication: "none",
  });
}
