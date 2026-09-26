import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FilePage } from "./types";

const apiMocks = vi.hoisted(() => ({
  listFiles: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

import { fileKeys, useFilesQuery } from "./queries";

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function wrapper(queryClient: QueryClient) {
  return function TestQueryClientProvider({
    children,
  }: {
    children: ReactNode;
  }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("File queries", () => {
  beforeEach(() => {
    apiMocks.listFiles.mockReset();
  });

  it("uses cursor and page size in the query key and request", async () => {
    const page: FilePage = { items: [], nextCursor: null };
    apiMocks.listFiles.mockResolvedValue(page);
    const queryClient = createTestQueryClient();

    const { result } = renderHook(() => useFilesQuery("cursor-2", 25), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fileKeys.page("cursor-2", 25)).toEqual([
      "files",
      "page",
      "cursor-2",
      25,
    ]);
    expect(apiMocks.listFiles).toHaveBeenCalledWith(
      { cursor: "cursor-2", limit: 25 },
      expect.any(AbortSignal),
    );
    expect(queryClient.getQueryData(fileKeys.page("cursor-2", 25))).toEqual(
      page,
    );
  });
});
