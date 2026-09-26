import { z } from "zod";

import { apiRequest } from "../../services/api/client";
import {
  FILE_LIBRARY_PAGE_SIZE,
  MAX_UPLOAD_CONTEXT_LENGTH,
  type FileMetadata,
  type FilePage,
  type InitiatedFileUpload,
} from "./types";

const timestampSchema = z.string().datetime({ offset: true });
const nonblankStringSchema = z
  .string()
  .refine((value) => value.trim().length > 0);

const fileMetadataSchema = z
  .object({
    public_id: z.string().uuid(),
    original_name: z.string(),
    mime_type: z.string(),
    size_bytes: z.number().int().nonnegative().nullable(),
    storage_status: z.enum(["pending", "available", "failed"]),
    created_at: timestampSchema,
    updated_at: timestampSchema,
  })
  .strict();

const filePageSchema = z
  .object({
    items: z.array(fileMetadataSchema),
    next_cursor: z.string().min(1).nullable(),
  })
  .strict();

const initiatedFileUploadSchema = z
  .object({
    upload: z
      .object({
        url: nonblankStringSchema,
        method: nonblankStringSchema,
        headers: z.record(z.string()),
        metadata: z
          .object({
            nexus_upload_context: nonblankStringSchema.pipe(
              z.string().max(MAX_UPLOAD_CONTEXT_LENGTH),
            ),
          })
          .strict(),
        expires_at: timestampSchema,
      })
      .strict(),
  })
  .strict();

function invalidFileResponse(): Error {
  return new Error("The File service returned an invalid response.");
}

export async function initiateFileUpload(
  file: File,
  signal?: AbortSignal,
): Promise<InitiatedFileUpload> {
  const response = await apiRequest<unknown>("/files/uploads", {
    method: "POST",
    body: {
      original_name: file.name,
      mime_type: file.type === "" ? null : file.type,
      size_bytes: file.size,
    },
    signal,
  });
  const parsed = initiatedFileUploadSchema.safeParse(response);
  if (!parsed.success) {
    throw invalidFileResponse();
  }

  return {
    upload: {
      url: parsed.data.upload.url,
      method: parsed.data.upload.method,
      headers: Object.freeze({ ...parsed.data.upload.headers }),
      metadata: Object.freeze({ ...parsed.data.upload.metadata }),
      expiresAt: parsed.data.upload.expires_at,
    },
  };
}


function mapFileMetadata(
  value: z.infer<typeof fileMetadataSchema>,
): FileMetadata {
  return Object.freeze({
    publicId: value.public_id,
    originalName: value.original_name,
    mimeType: value.mime_type,
    sizeBytes: value.size_bytes,
    storageStatus: value.storage_status,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  });
}

export async function listFiles(
  {
    cursor = null,
    limit = FILE_LIBRARY_PAGE_SIZE,
  }: {
    cursor?: string | null;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<FilePage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) {
    params.set("cursor", cursor);
  }

  const response = await apiRequest<unknown>(`/files?${params.toString()}`, {
    signal,
  });
  const parsed = filePageSchema.safeParse(response);
  if (!parsed.success) {
    throw invalidFileResponse();
  }

  return Object.freeze({
    items: Object.freeze(parsed.data.items.map(mapFileMetadata)),
    nextCursor: parsed.data.next_cursor,
  });
}
