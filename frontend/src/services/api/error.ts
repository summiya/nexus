interface ApiErrorPayload {
  error?: {
    code?: unknown;
    message?: unknown;
    request_id?: unknown;
  };
}

export class NexusApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = "UNKNOWN_ERROR",
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "NexusApiError";
  }
}

export async function toNexusApiError(
  response: Response,
): Promise<NexusApiError> {
  let payload: ApiErrorPayload | undefined;

  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    // A non-JSON upstream response is normalized below without exposing its body.
  }

  const error = payload?.error;
  const message =
    typeof error?.message === "string" && error.message.trim()
      ? error.message
      : `Request failed with status ${response.status}`;
  const code = typeof error?.code === "string" ? error.code : "UNKNOWN_ERROR";
  const requestId =
    typeof error?.request_id === "string" ? error.request_id : undefined;

  return new NexusApiError(message, response.status, code, requestId);
}
