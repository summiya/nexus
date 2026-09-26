import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { listFiles } from "./api";
import { FILE_LIBRARY_PAGE_SIZE } from "./types";

export const fileKeys = {
  all: ["files"] as const,
  page: (cursor: string | null, limit = FILE_LIBRARY_PAGE_SIZE) =>
    ["files", "page", cursor, limit] as const,
};

export function useFilesQuery(
  cursor: string | null,
  limit = FILE_LIBRARY_PAGE_SIZE,
) {
  return useQuery({
    queryKey: fileKeys.page(cursor, limit),
    queryFn: ({ signal }) => listFiles({ cursor, limit }, signal),
    placeholderData: keepPreviousData,
  });
}
