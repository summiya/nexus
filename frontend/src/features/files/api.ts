import { z } from "zod";

import { apiRequest } from "../../services/api/client";
import type { InitiatedFileUpload } from "./types";

const timestampSchema = z.string().datetime({ offset: true });
const nonblankStringSchema = z
  .string()
  .refine((value) => value.trim().length > 0);

const initiatedFileUploadSchema = z
  .object({
    file: z
      .object({
        public_id: z.string().uuid(),
        original_name: z.string(),
        mime_type: z.string(),
        storage_status: z.literal("pending"),
        created_at: timestampSchema,
      })
      .strict(),
    upload: z
      .object({
        url: nonblankStringSchema,
        method: nonblankStringSchema,
        headers: z.record(z.string()),
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
    file: {
      publicId: parsed.data.file.public_id,
      originalName: parsed.data.file.original_name,
      mimeType: parsed.data.file.mime_type,
      storageStatus: parsed.data.file.storage_status,
      createdAt: parsed.data.file.created_at,
    },
    upload: {
      url: parsed.data.upload.url,
      method: parsed.data.upload.method,
      headers: Object.freeze({ ...parsed.data.upload.headers }),
      expiresAt: parsed.data.upload.expires_at,
    },
  };
}
