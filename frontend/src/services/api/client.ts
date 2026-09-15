import { env } from '../../config/env';
import { toNexusApiError } from './error';

type ApiRequestOptions = Omit<RequestInit, 'body'> & {
  body?: BodyInit | Record<string, unknown> | null;
};

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, headers, ...rest } = options;
  const requestHeaders = new Headers(headers);
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;

  if (body && !isFormData && !requestHeaders.has('Content-Type')) {
    requestHeaders.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    ...rest,
    body:
      body && typeof body !== 'string' && !isFormData
        ? JSON.stringify(body)
        : (body as BodyInit | null),
    headers: requestHeaders,
  });

  if (!response.ok) {
    throw await toNexusApiError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function getHealth() {
  return apiRequest<{ status: string }>('/health');
}
