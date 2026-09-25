export const MAX_FILE_SIZE_BYTES = 512 * 1024 * 1024;

export interface PendingFileSummary {
  publicId: string;
  originalName: string;
  mimeType: string;
  storageStatus: "pending";
  createdAt: string;
}

export interface UploadGrant {
  url: string;
  method: string;
  headers: Readonly<Record<string, string>>;
  expiresAt: string;
}

export interface InitiatedFileUpload {
  file: PendingFileSummary;
  upload: UploadGrant;
}
