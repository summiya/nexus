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
