import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureApiAuthentication } from "../../services/api/client";
import { NexusApiError } from "../../services/api/error";
import { initiateFileUpload } from "./api";

const fileId = "11111111-1111-4111-8111-111111111111";
const createdAt = "2026-09-25T10:00:00Z";
const expiresAt = "2026-09-25T10:10:00Z";
const signedUrl =
  "https://account.blob.core.windows.net/files/blob?sv=2026-04-06&sig=SENSITIVE";

function jsonResponse(body: unknown, status = 201): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function validResponse() {
  return {
    file: {
      public_id: fileId,
      original_name: "report.pdf",
      mime_type: "application/pdf",
      storage_status: "pending",
      created_at: createdAt,
    },
    upload: {
      url: signedUrl,
      method: "PUT",
      headers: { "X-MS-Blob-Type": "BlockBlob" },
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
      file: {
        publicId: fileId,
        originalName: "report.pdf",
        mimeType: "application/pdf",
        storageStatus: "pending",
        createdAt,
      },
      upload: {
        url: signedUrl,
        method: "PUT",
        headers: { "X-MS-Blob-Type": "BlockBlob" },
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
  });

  it.each([
    { ...validResponse(), unexpected: true },
    { ...validResponse(), file: { ...validResponse().file, public_id: "bad" } },
    {
      ...validResponse(),
      file: { ...validResponse().file, storage_status: "available" },
    },
    { ...validResponse(), upload: { ...validResponse().upload, url: "   " } },
    {
      ...validResponse(),
      upload: { ...validResponse().upload, headers: { authorization: 123 } },
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
