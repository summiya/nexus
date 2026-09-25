import { z } from "zod";

import { apiRequest } from "../../services/api/client";
import { MAX_UPLOAD_CONTEXT_LENGTH, type InitiatedFileUpload } from "./types";

const timestampSchema = z.string().datetime({ offset: true });
const nonblankStringSchema = z
  .string()
  .refine((value) => value.trim().length > 0);

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
