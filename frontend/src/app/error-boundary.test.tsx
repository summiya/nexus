import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppErrorBoundary } from "./error-boundary";

function BrokenComponent(): never {
  throw new Error("sensitive internal failure");
}

describe("AppErrorBoundary", () => {
  it("shows a safe fallback without exposing the internal error", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <AppErrorBoundary>
        <BrokenComponent />
      </AppErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(
      screen.getByRole("button", { name: "Reload application" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("sensitive internal failure"),
    ).not.toBeInTheDocument();
  });
});
