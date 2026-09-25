import { beforeEach, describe, expect, it, vi } from "vitest";

const azureMocks = vi.hoisted(() => ({
  constructor: vi.fn(),
  uploadData: vi.fn(),
}));

vi.mock("@azure/storage-blob", () => ({
  BlockBlobClient: class {
    constructor(url: string) {
      azureMocks.constructor(url);
    }

    uploadData = azureMocks.uploadData;
  },
}));

import { MAX_UPLOAD_CONTEXT_LENGTH, type UploadGrant } from "./types";
import {
  FILE_UPLOAD_BLOCK_SIZE_BYTES,
  FILE_UPLOAD_CONCURRENCY,
  FILE_UPLOAD_SINGLE_SHOT_SIZE_BYTES,
  uploadGrantedFile,
} from "./upload";

const signedUrl =
  "https://account.blob.core.windows.net/files/blob?sv=2026-04-06&sig=SENSITIVE";

function grant(overrides: Partial<UploadGrant> = {}): UploadGrant {
  return {
    url: signedUrl,
    method: "PUT",
    headers: { "x-ms-blob-type": "BlockBlob" },
    metadata: { nexus_upload_context: "nuc1.primary.OPAQUE_CONTEXT" },
    expiresAt: "2026-09-25T10:10:00Z",
    ...overrides,
  };
}

describe("Azure File upload transport", () => {
  beforeEach(() => {
    azureMocks.constructor.mockReset();
    azureMocks.uploadData.mockReset();
    azureMocks.uploadData.mockResolvedValue({});
  });

  it("passes the exact signed URL and original File to the configured SDK upload", async () => {
    const file = new File(["contents"], "report.pdf", {
      type: "application/pdf",
    });
    const signal = new AbortController().signal;
    const onProgress = vi.fn();

    await uploadGrantedFile({ file, grant: grant(), signal, onProgress });

    expect(azureMocks.constructor).toHaveBeenCalledWith(signedUrl);
    expect(azureMocks.uploadData).toHaveBeenCalledWith(
      file,
      expect.objectContaining({
        abortSignal: signal,
        blobHTTPHeaders: { blobContentType: "application/pdf" },
        blockSize: FILE_UPLOAD_BLOCK_SIZE_BYTES,
        concurrency: FILE_UPLOAD_CONCURRENCY,
        maxSingleShotSize: FILE_UPLOAD_SINGLE_SHOT_SIZE_BYTES,
        metadata: { nexus_upload_context: "nuc1.primary.OPAQUE_CONTEXT" },
      }),
    );
    expect(FILE_UPLOAD_BLOCK_SIZE_BYTES).toBe(8 * 1024 * 1024);
    expect(FILE_UPLOAD_CONCURRENCY).toBe(4);
    expect(FILE_UPLOAD_SINGLE_SHOT_SIZE_BYTES).toBe(64 * 1024 * 1024);
  });

  it("does not read or buffer the File before handing it to the SDK", async () => {
    const file = new File(["contents"], "report.bin");
    const arrayBuffer = vi.fn();
    Object.defineProperty(file, "arrayBuffer", { value: arrayBuffer });

    await uploadGrantedFile({
      file,
      grant: grant(),
      signal: new AbortController().signal,
      onProgress: vi.fn(),
    });

    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("uses the binary MIME fallback and forwards SDK progress", async () => {
    const onProgress = vi.fn();
    azureMocks.uploadData.mockImplementation(
      async (_file: File, options: { onProgress: (event: object) => void }) => {
        options.onProgress({ loadedBytes: 5 });
      },
    );

    await uploadGrantedFile({
      file: new File(["value"], "no-type"),
      grant: grant(),
      signal: new AbortController().signal,
      onProgress,
    });

    expect(azureMocks.uploadData).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({
        blobHTTPHeaders: { blobContentType: "application/octet-stream" },
      }),
    );
    expect(onProgress).toHaveBeenCalledWith(5);
  });

  it.each([
    ["incompatible method", grant({ method: "POST" })],
    ["missing blob type", grant({ headers: {} })],
    ["wrong blob type", grant({ headers: { "x-ms-blob-type": "PageBlob" } })],
    [
      "unexpected control header",
      grant({
        headers: {
          "x-ms-blob-type": "BlockBlob",
          "x-ms-meta-private": "unexpected-value",
        },
      }),
    ],
    ["missing upload context", grant({ metadata: {} as never })],
    [
      "blank upload context",
      grant({ metadata: { nexus_upload_context: " " } }),
    ],
    [
      "unexpected metadata",
      grant({
        metadata: {
          nexus_upload_context: "nuc1.primary.OPAQUE_CONTEXT",
          extra: "unsupported",
        } as never,
      }),
    ],
  ])("fails closed for an %s", async (_description, incompatibleGrant) => {
    await expect(
      uploadGrantedFile({
        file: new File(["value"], "file.bin"),
        grant: incompatibleGrant,
        signal: new AbortController().signal,
        onProgress: vi.fn(),
      }),
    ).rejects.toThrow("The file could not be uploaded.");

    expect(azureMocks.constructor).not.toHaveBeenCalled();
    expect(azureMocks.uploadData).not.toHaveBeenCalled();
  });

  it("accepts the HTTP case-insensitive spelling of the supported header name", async () => {
    await uploadGrantedFile({
      file: new File(["value"], "file.bin"),
      grant: grant({ headers: { "X-MS-Blob-Type": "BlockBlob" } }),
      signal: new AbortController().signal,
      onProgress: vi.fn(),
    });

    expect(azureMocks.uploadData).toHaveBeenCalledOnce();
  });

  it("accepts an upload context at the transport length limit", async () => {
    const context = "x".repeat(MAX_UPLOAD_CONTEXT_LENGTH);

    await uploadGrantedFile({
      file: new File(["value"], "file.bin"),
      grant: grant({ metadata: { nexus_upload_context: context } }),
      signal: new AbortController().signal,
      onProgress: vi.fn(),
    });

    expect(azureMocks.uploadData).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({
        metadata: { nexus_upload_context: context },
      }),
    );
  });

  it("rejects an upload context over the transport length limit", async () => {
    await expect(
      uploadGrantedFile({
        file: new File(["value"], "file.bin"),
        grant: grant({
          metadata: {
            nexus_upload_context: "x".repeat(MAX_UPLOAD_CONTEXT_LENGTH + 1),
          },
        }),
        signal: new AbortController().signal,
        onProgress: vi.fn(),
      }),
    ).rejects.toThrow("The file could not be uploaded.");

    expect(azureMocks.constructor).not.toHaveBeenCalled();
    expect(azureMocks.uploadData).not.toHaveBeenCalled();
  });

  it("sanitizes provider errors without exposing the signed URL", async () => {
    azureMocks.uploadData.mockRejectedValue(
      new Error(`provider rejected ${signedUrl}`),
    );

    let thrown: unknown;
    try {
      await uploadGrantedFile({
        file: new File(["value"], "file.bin"),
        grant: grant(),
        signal: new AbortController().signal,
        onProgress: vi.fn(),
      });
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toEqual(new Error("The file could not be uploaded."));
    expect(String(thrown)).not.toContain("SENSITIVE");
  });

  it("reports cancellation safely", async () => {
    const controller = new AbortController();
    controller.abort();
    azureMocks.uploadData.mockRejectedValue(new Error("raw abort detail"));

    await expect(
      uploadGrantedFile({
        file: new File(["value"], "file.bin"),
        grant: grant(),
        signal: controller.signal,
        onProgress: vi.fn(),
      }),
    ).rejects.toThrow("The upload was cancelled.");
  });
});
