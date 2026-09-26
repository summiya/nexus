import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  deleteFile: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    deleteFile: apiMocks.deleteFile,
  };
});

import { FileDeleteButton } from "./FileDeleteButton";

function renderButton() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <FileDeleteButton
        filePublicId="11111111-1111-4111-8111-111111111111"
        originalName="report.pdf"
      />
    </QueryClientProvider>,
  );
  return invalidateSpy;
}

describe("FileDeleteButton", () => {
  beforeEach(() => {
    apiMocks.deleteFile.mockReset();
    vi.restoreAllMocks();
  });

  it("requires confirmation naming the File before deleting", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.deleteFile.mockResolvedValue(undefined);
    renderButton();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(confirmSpy).toHaveBeenCalledWith(
      'Delete "report.pdf"? This cannot be undone.',
    );
    expect(apiMocks.deleteFile).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
    );
  });

  it("cancel performs no delete request", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderButton();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(apiMocks.deleteFile).not.toHaveBeenCalled();
  });

  it("shows busy state and prevents repeated deletion", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let resolve!: () => void;
    apiMocks.deleteFile.mockReturnValue(
      new Promise<void>((resolvePromise) => {
        resolve = resolvePromise;
      }),
    );
    renderButton();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    const busy = screen.getByRole("button", { name: "Deleting…" });
    expect(busy).toBeDisabled();
    await user.click(busy);
    expect(apiMocks.deleteFile).toHaveBeenCalledOnce();

    resolve();
    expect(
      await screen.findByRole("button", { name: "Delete" }),
    ).toBeEnabled();
  });

  it("invalidates File list queries after success", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.deleteFile.mockResolvedValue(undefined);
    const invalidateSpy = renderButton();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["files"] });
  });

  it("shows only a safe error message on failure", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.deleteFile.mockRejectedValue(
      new Error("azure secret storage details"),
    );
    renderButton();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "File could not be deleted. Try again.",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("azure secret");
  });
});
