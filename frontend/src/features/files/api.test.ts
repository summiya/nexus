import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureApiAuthentication } from "../../services/api/client";
import { NexusApiError } from "../../services/api/error";
import {
  initiateFileUpload,
  listFiles,
  requestFileDownload,
} from "./api";

const expiresAt = "2026-09-25T10:10:00Z";
const signedUrl =
  "https://account.blob.core.windows.net/files/blob?sv=2026-04-06&sig=SENSITIVE";

const protectedContext = "nuc1.primary.OPAQUE_CONTEXT";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function validResponse() {
  return {
    upload: {
      url: signedUrl,
      method: "PUT",
      headers: { "X-MS-Blob-Type": "BlockBlob" },
      metadata: { nexus_upload_context: protectedContext },
      expires_at: expiresAt,
    },
  };
}

function browserFile(type = "application/pdf"): File {
  return new File(["contents"], "report.pdf", { type });
}

describe("File upload initiation API", () => {
  beforeEach(() => {
    configureApiAuthentication(undefined);
  });

  afterEach(() => {
    configureApiAuthentication(undefined);
  });

  it("uses the authenticated upload endpoint and maps the strict response", async () => {
    configureApiAuthentication({
      getAccessToken: () => "nexus-access-token",
      refreshAccessToken: vi.fn(),
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(validResponse()));
    const file = browserFile();

    await expect(initiateFileUpload(file)).resolves.toEqual({
      upload: {
        url: signedUrl,
        method: "PUT",
        headers: { "X-MS-Blob-Type": "BlockBlob" },
        metadata: { nexus_upload_context: protectedContext },
        expiresAt,
      },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/files/uploads",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          original_name: "report.pdf",
          mime_type: "application/pdf",
          size_bytes: file.size,
        }),
      }),
    );
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer nexus-access-token");
  });

  it("sends null when the browser provides no MIME type", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(validResponse()));

    await initiateFileUpload(browserFile(""));

    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({
          original_name: "report.pdf",
          mime_type: null,
          size_bytes: 8,
        }),
      }),
    );
  });

  it("preserves signed provider instructions exactly and exposes headers read-only", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(validResponse()),
    );

    const result = await initiateFileUpload(browserFile());

    expect(result.upload.url).toBe(signedUrl);
    expect(Object.keys(result.upload.headers)).toEqual(["X-MS-Blob-Type"]);
    expect(result.upload.headers["X-MS-Blob-Type"]).toBe("BlockBlob");
    expect(Object.isFrozen(result.upload.headers)).toBe(true);
    expect(result.upload.metadata.nexus_upload_context).toBe(protectedContext);
    expect(Object.isFrozen(result.upload.metadata)).toBe(true);
  });

  it.each([
    { ...validResponse(), unexpected: true },
    {
      ...validResponse(),
      file: { public_id: "unexpected-persisted-file" },
    },
    { ...validResponse(), upload: { ...validResponse().upload, url: "   " } },
    {
      ...validResponse(),
      upload: { ...validResponse().upload, headers: { authorization: 123 } },
    },
    {
      ...validResponse(),
      upload: { ...validResponse().upload, metadata: {} },
    },
    {
      ...validResponse(),
      upload: {
        ...validResponse().upload,
        metadata: {
          nexus_upload_context: protectedContext,
          extra: "unsupported",
        },
      },
    },
  ])("rejects a malformed successful response safely", async (body) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(body));

    let thrown: unknown;
    try {
      await initiateFileUpload(browserFile());
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toEqual(
      new Error("The File service returned an invalid response."),
    );
    expect(String(thrown)).not.toContain("SENSITIVE");
  });

  it("propagates the normalized Nexus API error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "FORBIDDEN",
            message: "File uploads are not allowed.",
          },
        },
        403,
      ),
    );

    await expect(initiateFileUpload(browserFile())).rejects.toEqual(
      new NexusApiError("File uploads are not allowed.", 403, "FORBIDDEN"),
    );
  });

  it("propagates the original network failure", async () => {
    const networkError = new TypeError("network unavailable");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(networkError);

    await expect(initiateFileUpload(browserFile())).rejects.toBe(networkError);
  });
});

describe("File Library API", () => {
  it("requests the first page without a cursor and maps strict metadata", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [
          {
            public_id: "11111111-1111-4111-8111-111111111111",
            original_name: "report.pdf",
            mime_type: "application/pdf",
            size_bytes: 2048,
            storage_status: "available",
            created_at: "2026-09-26T12:00:00Z",
            updated_at: "2026-09-26T12:01:00Z",
          },
        ],
        next_cursor: "opaque-next",
      }),
    );

    await expect(listFiles()).resolves.toEqual({
      items: [
        {
          publicId: "11111111-1111-4111-8111-111111111111",
          originalName: "report.pdf",
          mimeType: "application/pdf",
          sizeBytes: 2048,
          storageStatus: "available",
          createdAt: "2026-09-26T12:00:00Z",
          updatedAt: "2026-09-26T12:01:00Z",
        },
      ],
      nextCursor: "opaque-next",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/files?limit=50",
      expect.any(Object),
    );
  });

  it("passes the backend cursor unchanged and supports null file size", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [
          {
            public_id: "22222222-2222-4222-8222-222222222222",
            original_name: "pending.txt",
            mime_type: "text/plain",
            size_bytes: null,
            storage_status: "pending",
            created_at: "2026-09-26T12:00:00Z",
            updated_at: "2026-09-26T12:00:00Z",
          },
        ],
        next_cursor: null,
      }),
    );

    const page = await listFiles({ cursor: "opaque cursor/+", limit: 25 });

    expect(page.items[0]?.sizeBytes).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/files?limit=25&cursor=opaque+cursor%2F%2B",
      expect.any(Object),
    );
  });

  it.each([
    {
      items: [],
      next_cursor: null,
      unexpected: true,
    },
    {
      items: [
        {
          public_id: "11111111-1111-4111-8111-111111111111",
          original_name: "report.pdf",
          mime_type: "application/pdf",
          size_bytes: 10,
          storage_status: "scanning",
          created_at: "2026-09-26T12:00:00Z",
          updated_at: "2026-09-26T12:00:00Z",
        },
      ],
      next_cursor: null,
    },
    {
      items: [
        {
          public_id: "11111111-1111-4111-8111-111111111111",
          original_name: "report.pdf",
          mime_type: "application/pdf",
          size_bytes: 10,
          storage_status: "available",
          created_at: "2026-09-26T12:00:00Z",
          updated_at: "2026-09-26T12:00:00Z",
          storage_key: "files/private",
        },
      ],
      next_cursor: null,
    },
  ])("rejects incompatible File list responses", async (body) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(body));

    await expect(listFiles()).rejects.toEqual(
      new Error("The File service returned an invalid response."),
    );
  });
});



describe("File download API", () => {
  it("requests an ephemeral download grant with POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        url: signedUrl,
        expires_at: expiresAt,
      }),
    );

    await expect(
      requestFileDownload("11111111-1111-4111-8111-111111111111"),
    ).resolves.toEqual({
      url: signedUrl,
      expiresAt,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/files/11111111-1111-4111-8111-111111111111/download",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it.each([
    {
      url: signedUrl,
      expires_at: expiresAt,
      storage_key: "files/private",
    },
    {
      url: "not-a-url",
      expires_at: expiresAt,
    },
    {
      url: signedUrl,
      expires_at: "not-a-timestamp",
    },
  ])("rejects incompatible download grant responses", async (body) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(body));

    await expect(
      requestFileDownload("11111111-1111-4111-8111-111111111111"),
    ).rejects.toEqual(
      new Error("The File service returned an invalid response."),
    );
  });
});
