import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FilePage } from "./types";

const apiMocks = vi.hoisted(() => ({
  listFiles: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    listFiles: apiMocks.listFiles,
  };
});

import { FileLibrary } from "./FileLibrary";

const firstPage: FilePage = {
  items: [
    {
      publicId: "11111111-1111-4111-8111-111111111111",
      originalName: "report.pdf",
      mimeType: "application/pdf",
      sizeBytes: 2_400_000,
      storageStatus: "pending",
      createdAt: "2026-09-26T12:00:00Z",
      updatedAt: "2026-09-26T12:00:01Z",
    },
  ],
  nextCursor: "cursor-2",
};

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function renderLibrary(queryClient = createTestQueryClient()) {
  return render(
    <QueryClientProvider client={queryClient}>
      <FileLibrary />
    </QueryClientProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("FileLibrary", () => {
  beforeEach(() => {
    apiMocks.listFiles.mockReset();
  });

  it("renders metadata, status, and the pending security explanation", async () => {
    apiMocks.listFiles.mockResolvedValue(firstPage);
    renderLibrary();

    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("application/pdf")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(
      screen.getByText("Being checked for security"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });

  it("renders the first-page loading state", () => {
    apiMocks.listFiles.mockReturnValue(new Promise(() => undefined));
    renderLibrary();

    expect(screen.getByRole("status")).toHaveTextContent("Loading files");
  });

  it("renders the empty state", async () => {
    apiMocks.listFiles.mockResolvedValue({ items: [], nextCursor: null });
    renderLibrary();

    expect(await screen.findByText("No files yet.")).toBeInTheDocument();
    expect(
      screen.getByText(/appear here after Nexus verifies it/i),
    ).toBeInTheDocument();
  });

  it("renders a safe error and retries", async () => {
    const user = userEvent.setup();
    apiMocks.listFiles
      .mockRejectedValueOnce(new Error("private backend detail"))
      .mockResolvedValueOnce(firstPage);
    renderLibrary();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Files are temporarily unavailable.",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(
      "private backend detail",
    );

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    expect(apiMocks.listFiles).toHaveBeenCalledTimes(2);
  });

  it("keeps current rows visible and disables navigation while the next page loads", async () => {
    const user = userEvent.setup();
    const secondPage = deferred<FilePage>();
    apiMocks.listFiles
      .mockResolvedValueOnce(firstPage)
      .mockReturnValueOnce(secondPage.promise);
    renderLibrary();

    expect(await screen.findByText("report.pdf")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => {
      expect(apiMocks.listFiles).toHaveBeenLastCalledWith(
        { cursor: "cursor-2", limit: 50 },
        expect.any(AbortSignal),
      );
    });

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Loading page");

    secondPage.resolve({
      items: [
        {
          ...firstPage.items[0],
          publicId: "22222222-2222-4222-8222-222222222222",
          originalName: "second.pdf",
          storageStatus: "available",
        },
      ],
      nextCursor: null,
    });

    expect(await screen.findByText("second.pdf")).toBeInTheDocument();
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("returns to the prior backend cursor without reconstructing one", async () => {
    const user = userEvent.setup();
    const secondPage: FilePage = {
      items: [
        {
          ...firstPage.items[0],
          publicId: "22222222-2222-4222-8222-222222222222",
          originalName: "second.pdf",
          storageStatus: "available",
        },
      ],
      nextCursor: null,
    };
    apiMocks.listFiles
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage)
      .mockResolvedValueOnce(firstPage);
    renderLibrary();

    await screen.findByText("report.pdf");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("second.pdf");
    await user.click(screen.getByRole("button", { name: "Previous" }));

    await waitFor(() => {
      expect(apiMocks.listFiles).toHaveBeenLastCalledWith(
        { cursor: null, limit: 50 },
        expect.any(AbortSignal),
      );
    });
    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
  });
});
