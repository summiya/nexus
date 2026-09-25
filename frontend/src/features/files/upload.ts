import type { UploadGrant } from "./types";

export const FILE_UPLOAD_BLOCK_SIZE_BYTES = 8 * 1024 * 1024;
export const FILE_UPLOAD_CONCURRENCY = 4;
export const FILE_UPLOAD_SINGLE_SHOT_SIZE_BYTES = 64 * 1024 * 1024;

const uploadFailureMessage = "The file could not be uploaded.";
const requiredBlobTypeHeader = "x-ms-blob-type";
const requiredContextMetadataKey = "nexus_upload_context";

interface UploadGrantedFileInput {
  file: File;
  grant: UploadGrant;
  signal: AbortSignal;
  onProgress: (loadedBytes: number) => void;
}

function grantIsSupported(grant: UploadGrant): boolean {
  const headers = Object.entries(grant.headers);
  const metadata = Object.entries(grant.metadata);
  return (
    grant.method === "PUT" &&
    headers.length === 1 &&
    headers[0][0].toLowerCase() === requiredBlobTypeHeader &&
    headers[0][1] === "BlockBlob" &&
    metadata.length === 1 &&
    metadata[0][0] === requiredContextMetadataKey &&
    metadata[0][1].trim().length > 0
  );
}

export async function uploadGrantedFile({
  file,
  grant,
  signal,
  onProgress,
}: UploadGrantedFileInput): Promise<void> {
  if (!grantIsSupported(grant)) {
    throw new Error(uploadFailureMessage);
  }

  try {
    const { BlockBlobClient } = await import("@azure/storage-blob");
    const client = new BlockBlobClient(grant.url);
    await client.uploadData(file, {
      abortSignal: signal,
      blobHTTPHeaders: {
        blobContentType:
          file.type === "" ? "application/octet-stream" : file.type,
      },
      blockSize: FILE_UPLOAD_BLOCK_SIZE_BYTES,
      concurrency: FILE_UPLOAD_CONCURRENCY,
      maxSingleShotSize: FILE_UPLOAD_SINGLE_SHOT_SIZE_BYTES,
      metadata: { ...grant.metadata },
      onProgress: ({ loadedBytes }) => onProgress(loadedBytes),
    });
  } catch {
    throw new Error(
      signal.aborted ? "The upload was cancelled." : uploadFailureMessage,
    );
  }
}
