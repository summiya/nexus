import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FilePage } from "./types";

const queryMock = vi.hoisted(() => ({
  refetch: vi.fn(),
  state: {
    data: undefined as FilePage | undefined,
    isError: false,
    isFetching: false,
    isPending: false,
    isPlaceholderData: false,
  },
}));

vi.mock("./queries", () => ({
  useFilesQuery: vi.fn(() => queryMock.state),
}));

import { useFilesQuery } from "./queries";
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

describe("FileLibrary", () => {
  beforeEach(() => {
    queryMock.refetch.mockReset();
    queryMock.state.data = firstPage;
    queryMock.state.isError = false;
    queryMock.state.isFetching = false;
    queryMock.state.isPending = false;
    queryMock.state.isPlaceholderData = false;
  });

  it("renders metadata, status, and pending security explanation", () => {
    render(<FileLibrary />);

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("application/pdf")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(
      screen.getByText("Being checked for security"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });

  it("renders loading, empty, and error states safely", async () => {
    const { rerender } = render(<FileLibrary />);

    queryMock.state.data = undefined;
    queryMock.state.isPending = true;
    rerender(<FileLibrary />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading files");

    queryMock.state.isPending = false;
    queryMock.state.data = { items: [], nextCursor: null };
    rerender(<FileLibrary />);
    expect(screen.getByText("No files yet.")).toBeInTheDocument();

    queryMock.state.data = undefined;
    queryMock.state.isError = true;
    rerender(<FileLibrary />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Files are temporarily unavailable.",
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(queryMock.refetch).toHaveBeenCalledOnce();
  });

  it("keeps current rows visible and disables navigation during page fetch", async () => {
    const user = userEvent.setup();
    render(<FileLibrary />);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(useFilesQuery).toHaveBeenLastCalledWith("cursor-2");

    queryMock.state.data = firstPage;
    queryMock.state.isFetching = true;
    queryMock.state.isPlaceholderData = true;

    render(<FileLibrary />);

    expect(screen.getAllByText("report.pdf").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Previous" }).at(-1)).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Next" }).at(-1)).toBeDisabled();
    expect(screen.getAllByRole("status").at(-1)).toHaveTextContent(
      "Loading page",
    );
  });

  it("uses backend cursors for next and restores the prior cursor", async () => {
    const user = userEvent.setup();
    render(<FileLibrary />);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(useFilesQuery).toHaveBeenLastCalledWith("cursor-2");

    queryMock.state.data = {
      items: [
        {
          ...firstPage.items[0],
          publicId: "22222222-2222-4222-8222-222222222222",
          originalName: "second.pdf",
        },
      ],
      nextCursor: null,
    };

    const { rerender } = render(<FileLibrary />);
    rerender(<FileLibrary />);

    const previousButtons = screen.getAllByRole("button", { name: "Previous" });
    await user.click(previousButtons[previousButtons.length - 1]);
    expect(useFilesQuery).toHaveBeenLastCalledWith(null);
  });
});
