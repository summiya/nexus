import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AccountSettingsSection } from "./AccountSettingsSection";

describe("NEXUS account settings design", () => {
  it("keeps profile changes local to the design preview", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AccountSettingsSection section="profile" />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "Profile" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /interface placeholder until profile identity is connected/,
      ),
    ).toBeInTheDocument();

    await user.type(
      screen.getByRole("textbox", { name: "Display name" }),
      "Sample User",
    );
    await user.click(screen.getByRole("button", { name: "Save preview" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "Profile preview updated on this page only.",
    );
  });

  it("changes illustrative appearance preferences without changing the global theme", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AccountSettingsSection section="preferences" />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "Compact" }));
    expect(screen.getByRole("button", { name: "Compact" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(
      screen.getByRole("button", { name: "Preview interface motion" }),
    );
    expect(screen.getByText("PREVIEW / MOTION OFF")).toBeInTheDocument();
  });

  it("does not invent organization usage or billing figures", () => {
    render(
      <MemoryRouter>
        <AccountSettingsSection section="usage" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Usage" })).toBeInTheDocument();
    expect(screen.getByText("No token metering connected")).toBeInTheDocument();
    expect(
      screen.getByText(/Values are intentionally not fabricated/),
    ).toBeInTheDocument();
  });
});
