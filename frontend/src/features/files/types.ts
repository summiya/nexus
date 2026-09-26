export const MAX_FILE_SIZE_BYTES = 512 * 1024 * 1024;
export const MAX_UPLOAD_CONTEXT_LENGTH = 4096;

export interface UploadGrant {
  url: string;
  method: string;
  headers: Readonly<Record<string, string>>;
  metadata: Readonly<{
    nexus_upload_context: string;
  }>;
  expiresAt: string;
}

export interface InitiatedFileUpload {
  upload: UploadGrant;
}


export const FILE_LIBRARY_PAGE_SIZE = 50;

export type FileStorageStatus = "pending" | "available" | "failed";

export interface FileMetadata {
  publicId: string;
  originalName: string;
  mimeType: string;
  sizeBytes: number | null;
  storageStatus: FileStorageStatus;
  createdAt: string;
  updatedAt: string;
}

export interface FilePage {
  items: readonly FileMetadata[];
  nextCursor: string | null;
}
