import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fileMocks = vi.hoisted(() => ({
  initiateFileUpload: vi.fn(),
  uploadGrantedFile: vi.fn(),
}));

vi.mock("./api", () => ({
  initiateFileUpload: fileMocks.initiateFileUpload,
}));
vi.mock("./upload", () => ({
  uploadGrantedFile: fileMocks.uploadGrantedFile,
}));

import { MAX_FILE_SIZE_BYTES, type InitiatedFileUpload } from "./types";
import { useFileUpload } from "./useFileUpload";

const initiatedUpload: InitiatedFileUpload = {
  upload: {
    url: "https://account.blob.core.windows.net/file?sig=SENSITIVE",
    method: "PUT",
    headers: { "x-ms-blob-type": "BlockBlob" },
    metadata: { nexus_upload_context: "nuc1.primary.OPAQUE_CONTEXT" },
    expiresAt: "2026-09-25T10:10:00Z",
  },
};

function fileWithSize(size: number): File {
  const file = new File(["content"], "report.pdf", {
    type: "application/pdf",
  });
  Object.defineProperty(file, "size", { configurable: true, value: size });
  return file;
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("useFileUpload", () => {
  beforeEach(() => {
    fileMocks.initiateFileUpload.mockReset();
    fileMocks.uploadGrantedFile.mockReset();
    fileMocks.initiateFileUpload.mockResolvedValue(initiatedUpload);
    fileMocks.uploadGrantedFile.mockResolvedValue(undefined);
  });

  it("accepts exactly 512 MiB and completes the initiation then transfer flow", async () => {
    const { result } = renderHook(useFileUpload);
    const file = fileWithSize(MAX_FILE_SIZE_BYTES);

    await act(() => result.current.startUpload(file));

    expect(fileMocks.initiateFileUpload).toHaveBeenCalledWith(
      file,
      expect.any(AbortSignal),
    );
    expect(fileMocks.uploadGrantedFile).toHaveBeenCalledWith(
      expect.objectContaining({
        file,
        grant: initiatedUpload.upload,
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result.current.phase).toBe("transferred");
    expect(result.current.progress).toBe(100);
    expect(result.current).not.toHaveProperty("file");
    expect(result.current).not.toHaveProperty("upload");
    expect(result.current).not.toHaveProperty("grant");
    expect(JSON.stringify(result.current)).not.toContain("OPAQUE_CONTEXT");
  });

  it("rejects one byte over the limit before any API or storage call", async () => {
    const { result } = renderHook(useFileUpload);

    await act(() =>
      result.current.startUpload(fileWithSize(MAX_FILE_SIZE_BYTES + 1)),
    );

    expect(result.current.phase).toBe("failed");
    expect(result.current.feedback).toEqual({ kind: "file_too_large" });
    expect(fileMocks.initiateFileUpload).not.toHaveBeenCalled();
    expect(fileMocks.uploadGrantedFile).not.toHaveBeenCalled();
  });

  it("keeps zero-byte progress at zero until successful settlement", async () => {
    const transfer = deferred<void>();
    fileMocks.uploadGrantedFile.mockImplementation(
      async ({ onProgress }: { onProgress: (loadedBytes: number) => void }) => {
        onProgress(1);
        await transfer.promise;
      },
    );
    const { result } = renderHook(useFileUpload);
    let uploadPromise!: Promise<void>;

    act(() => {
      uploadPromise = result.current.startUpload(fileWithSize(0));
    });
    await waitFor(() => expect(result.current.phase).toBe("uploading"));
    expect(result.current.progress).toBe(0);

    transfer.resolve();
    await act(() => uploadPromise);
    expect(result.current.progress).toBe(100);
  });

  it("calculates clamped progress from transferred bytes", async () => {
    fileMocks.uploadGrantedFile.mockImplementation(
      async ({ onProgress }: { onProgress: (loadedBytes: number) => void }) => {
        onProgress(3);
        onProgress(99);
      },
    );
    const { result } = renderHook(useFileUpload);

    await act(() => result.current.startUpload(fileWithSize(8)));

    expect(result.current.progress).toBe(100);
  });

  it("classifies initiation failures safely and does not start storage", async () => {
    fileMocks.initiateFileUpload.mockRejectedValue(
      new Error("https://storage.example/?sig=SENSITIVE"),
    );
    const { result } = renderHook(useFileUpload);

    await act(() => result.current.startUpload(fileWithSize(8)));

    expect(result.current.phase).toBe("failed");
    expect(result.current.feedback).toEqual({ kind: "initiation_failure" });
    expect(fileMocks.uploadGrantedFile).not.toHaveBeenCalled();
    expect(JSON.stringify(result.current)).not.toContain("SENSITIVE");
  });

  it("classifies transfer failures safely without automatic retry", async () => {
    fileMocks.uploadGrantedFile.mockRejectedValue(new Error("provider detail"));
    const { result } = renderHook(useFileUpload);

    await act(() => result.current.startUpload(fileWithSize(8)));

    expect(result.current.phase).toBe("failed");
    expect(result.current.feedback).toEqual({ kind: "transfer_failure" });
    expect(fileMocks.initiateFileUpload).toHaveBeenCalledOnce();
    expect(fileMocks.uploadGrantedFile).toHaveBeenCalledOnce();
  });

  it("aborts and reports cancellation only after the active request settles", async () => {
    fileMocks.uploadGrantedFile.mockImplementation(
      async ({ signal }: { signal: AbortSignal }) =>
        new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new Error("aborted")), {
            once: true,
          });
        }),
    );
    const { result } = renderHook(useFileUpload);
    let uploadPromise!: Promise<void>;

    act(() => {
      uploadPromise = result.current.startUpload(fileWithSize(8));
    });
    await waitFor(() => expect(result.current.phase).toBe("uploading"));
    act(() => result.current.cancelUpload());
    await act(() => uploadPromise);

    expect(result.current.phase).toBe("cancelled");
    const signal = fileMocks.uploadGrantedFile.mock.calls[0][0]
      .signal as AbortSignal;
    expect(signal.aborted).toBe(true);
  });

  it("prevents a synchronous duplicate start", async () => {
    const initiation = deferred<InitiatedFileUpload>();
    fileMocks.initiateFileUpload.mockReturnValue(initiation.promise);
    const { result } = renderHook(useFileUpload);
    const file = fileWithSize(8);
    let first!: Promise<void>;
    let second!: Promise<void>;

    act(() => {
      first = result.current.startUpload(file);
      second = result.current.startUpload(file);
    });
    expect(fileMocks.initiateFileUpload).toHaveBeenCalledOnce();

    initiation.resolve(initiatedUpload);
    await act(async () => {
      await Promise.all([first, second]);
    });
    expect(fileMocks.uploadGrantedFile).toHaveBeenCalledOnce();
  });

  it("aborts on unmount and ignores late completion", async () => {
    const initiation = deferred<InitiatedFileUpload>();
    fileMocks.initiateFileUpload.mockReturnValue(initiation.promise);
    const { result, unmount } = renderHook(useFileUpload);
    const uploadPromise = result.current.startUpload(fileWithSize(8));
    const signal = fileMocks.initiateFileUpload.mock.calls[0][1] as AbortSignal;

    unmount();
    expect(signal.aborted).toBe(true);
    initiation.resolve(initiatedUpload);
    await uploadPromise;

    expect(fileMocks.uploadGrantedFile).not.toHaveBeenCalled();
  });
});
