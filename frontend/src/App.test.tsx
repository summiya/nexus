import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("renders the application through the provider and router composition", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Application foundation" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
  });

  it("redirects unknown routes to the home page", async () => {
    window.history.replaceState({}, "", "/does-not-exist");

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Application foundation" }),
    ).toBeInTheDocument();
  });
});
