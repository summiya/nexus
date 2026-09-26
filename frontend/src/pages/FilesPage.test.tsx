import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../features/files", () => ({
  FileLibrary: () => <section aria-label="File library">Library</section>,
  FileUploadPanel: () => <section aria-label="File upload">Upload</section>,
}));

import { FilesPage } from "./FilesPage";

describe("FilesPage", () => {
  it("composes upload and library capabilities without mixing their behavior", () => {
    render(<FilesPage />);

    expect(screen.getByRole("region", { name: "File upload" })).toBeVisible();
    expect(screen.getByRole("region", { name: "File library" })).toBeVisible();
  });
});
