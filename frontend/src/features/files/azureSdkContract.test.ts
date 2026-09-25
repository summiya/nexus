import {
  BlockBlobClient,
  type HttpOperationResponse,
  type IHttpClient,
  newPipeline,
  type WebResource,
} from "@azure/storage-blob";
import { describe, expect, it } from "vitest";

describe("Azure browser SDK compatibility", () => {
  it("sends a service version compatible with create-only block operations", async () => {
    const requests: WebResource[] = [];
    const httpClient: IHttpClient = {
      async sendRequest(request) {
        requests.push(request);
        return {
          request,
          status: 201,
          headers: request.headers,
        } as HttpOperationResponse;
      },
    };
    const client = new BlockBlobClient(
      "https://account.blob.core.windows.net/files/blob?sv=2026-04-06&sp=c&sig=test",
      newPipeline(undefined, { httpClient }),
    );

    await client.uploadData(new Uint8Array([1, 2, 3, 4]), {
      blockSize: 2,
      maxSingleShotSize: 1,
      metadata: { nexus_upload_context: "nuc1.primary.OPAQUE_CONTEXT" },
    });

    const blockRequests = requests.filter(
      (request) => new URL(request.url).searchParams.get("comp") === "block",
    );
    const blockListRequests = requests.filter(
      (request) =>
        new URL(request.url).searchParams.get("comp") === "blocklist",
    );
    expect(blockRequests).not.toHaveLength(0);
    expect(blockListRequests).toHaveLength(1);

    for (const request of requests) {
      const serviceVersion = request.headers.get("x-ms-version");
      expect(serviceVersion).not.toBeNull();
      expect(serviceVersion).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(serviceVersion! >= "2026-04-06").toBe(true);
      expect(request.headers.get("Authorization")).toBeUndefined();
    }
    expect(
      blockListRequests[0].headers.get("x-ms-meta-nexus_upload_context"),
    ).toBe("nuc1.primary.OPAQUE_CONTEXT");
  });
});
