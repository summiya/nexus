const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

type ApiRequestOptions = Omit<RequestInit, 'body'> & {
  body?: BodyInit | Record<string, unknown> | null;
};

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, headers, ...rest } = options;

  const requestHeaders = new Headers(headers);

  if (body && !(body instanceof FormData) && !requestHeaders.has('Content-Type')) {
    requestHeaders.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    body: body && typeof body !== 'string' && !(body instanceof FormData)
      ? JSON.stringify(body)
      : (body as BodyInit | null),
    headers: requestHeaders,
  });

  if (!response.ok) {
    const message = await response.text().catch(() => 'Request failed');
    throw new Error(message || `Request failed with status ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function getHealth() {
  return apiRequest<{ status: string }>('/health');
}
