import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hookMocks = vi.hoisted(() => ({
  cancelUpload: vi.fn(),
  reset: vi.fn(),
  startUpload: vi.fn(),
  state: {
    feedback: null as { kind: "transfer_failure" } | null,
    phase: "idle" as
      | "idle"
      | "initiating"
      | "uploading"
      | "transferred"
      | "failed"
      | "cancelled",
    progress: 0,
  },
}));

vi.mock("./useFileUpload", () => ({
  useFileUpload: () => ({
    ...hookMocks.state,
    cancelUpload: hookMocks.cancelUpload,
    reset: hookMocks.reset,
    startUpload: hookMocks.startUpload,
  }),
}));

import { MAX_FILE_SIZE_BYTES } from "./types";
import { FileUploadPanel } from "./FileUploadPanel";

function fileWithSize(size: number): File {
  const file = new File(["content"], "quarterly-report.pdf", {
    type: "application/pdf",
  });
  Object.defineProperty(file, "size", { configurable: true, value: size });
  return file;
}

describe("FileUploadPanel", () => {
  beforeEach(() => {
    hookMocks.cancelUpload.mockReset();
    hookMocks.reset.mockReset();
    hookMocks.startUpload.mockReset();
    hookMocks.startUpload.mockResolvedValue(undefined);
    hookMocks.state.feedback = null;
    hookMocks.state.phase = "idle";
    hookMocks.state.progress = 0;
  });

  it("renders an accessible single-file picker and the product limit", () => {
    render(<FileUploadPanel />);

    expect(
      screen.getByRole("heading", { name: "Upload a file" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Choose a file")).not.toHaveAttribute(
      "multiple",
    );
    expect(screen.getByText("Maximum file size: 512 MB.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Upload one file directly to secure storage. Nexus will verify it after the transfer completes.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });

  it("shows selected metadata and submits the selected File", async () => {
    const user = userEvent.setup();
    render(<FileUploadPanel />);
    const file = fileWithSize(1_024);

    await user.upload(screen.getByLabelText("Choose a file"), file);
    expect(screen.getByText("quarterly-report.pdf")).toBeInTheDocument();
    expect(screen.getByText("1,024 bytes")).toBeInTheDocument();
    expect(hookMocks.reset).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(hookMocks.startUpload).toHaveBeenCalledWith(file);
  });

  it("blocks an oversized selection without starting an upload", async () => {
    const user = userEvent.setup();
    render(<FileUploadPanel />);

    await user.upload(
      screen.getByLabelText("Choose a file"),
      fileWithSize(MAX_FILE_SIZE_BYTES + 1),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Maximum file size is 512 MB.",
    );
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    expect(hookMocks.startUpload).not.toHaveBeenCalled();
  });

  it("shows upload progress and supports cancellation", async () => {
    hookMocks.state.phase = "uploading";
    hookMocks.state.progress = 42;
    const user = userEvent.setup();
    render(<FileUploadPanel />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "42");
    expect(screen.getByText("42%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(hookMocks.cancelUpload).toHaveBeenCalledOnce();
  });

  it.each([
    ["transferred", "Upload completed. The file is awaiting verification."],
    ["cancelled", "Upload cancelled."],
  ] as const)("shows the safe %s state", (phase, message) => {
    hookMocks.state.phase = phase;
    render(<FileUploadPanel />);

    expect(screen.getByText(message)).toBeInTheDocument();
  });

  it("maps closed failure state to fixed safe copy", () => {
    hookMocks.state.phase = "failed";
    hookMocks.state.feedback = { kind: "transfer_failure" };
    render(<FileUploadPanel />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Upload failed. Please try again.",
    );
  });
});
