import { describe, expect, it } from "vitest";

import { NexusApiError, toNexusApiError } from "./error";

describe("toNexusApiError", () => {
  it("normalizes the canonical backend error envelope", async () => {
    const response = new Response(
      JSON.stringify({
        error: {
          code: "NOT_FOUND",
          message: "Resource not found.",
          request_id: "req_123",
        },
      }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );

    const error = await toNexusApiError(response);

    expect(error).toBeInstanceOf(NexusApiError);
    expect(error).toMatchObject({
      message: "Resource not found.",
      status: 404,
      code: "NOT_FOUND",
      requestId: "req_123",
    });
  });

  it("does not expose a non-JSON upstream response body", async () => {
    const response = new Response("internal stack trace: secret", {
      status: 500,
    });

    const error = await toNexusApiError(response);

    expect(error.message).toBe("Request failed with status 500");
    expect(error.message).not.toContain("secret");
  });
});
