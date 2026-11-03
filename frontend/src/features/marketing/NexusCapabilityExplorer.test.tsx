import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { NexusCapabilityExplorer } from "./NexusCapabilityExplorer";

function renderExplorer(authenticated = false) {
  return render(
    <MemoryRouter>
      <NexusCapabilityExplorer authenticated={authenticated} />
    </MemoryRouter>,
  );
}

describe("NEXUS capability explorer", () => {
  it("shows implemented tenant, RBAC and BYOK capabilities next to clearly labeled roadmap features", () => {
    renderExplorer();

    const grid = screen.getByLabelText("Explore NEXUS capabilities");
    expect(within(grid).getByRole("button", { name: /Multi-tenancy/ })).toBeInTheDocument();
    expect(within(grid).getByRole("button", { name: /RBAC & permissions/ })).toBeInTheDocument();
    expect(within(grid).getByRole("button", { name: /Bring your own key/ })).toBeInTheDocument();
    expect(within(grid).getByRole("button", { name: /MCP integrations/ })).toHaveTextContent("On the roadmap");
    expect(within(grid).getByRole("button", { name: /Retrieval \+ RAG/ })).toHaveTextContent("In development");
  });

  it("filters the browser, selects an upcoming MCP feature and never offers a non-existent route", async () => {
    const user = userEvent.setup();
    renderExplorer(true);

    const filters = screen.getByRole("group", { name: "Filter capabilities" });
    await user.click(within(filters).getByRole("button", { name: "On the roadmap" }));

    const grid = screen.getByLabelText("Explore NEXUS capabilities");
    expect(within(grid).queryByRole("button", { name: /Bring your own key/ })).not.toBeInTheDocument();
    await user.click(within(grid).getByRole("button", { name: /MCP integrations/ }));

    expect(screen.getByText(/There is no active MCP connector gallery yet/)).toBeInTheDocument();
    expect(screen.getByText(/Preview only · not enabled in the workspace yet/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open MCP/i })).not.toBeInTheDocument();
  });

  it("opens real settings destinations only for authenticated users", async () => {
    const rendered = renderExplorer(false);

    expect(screen.getByRole("link", { name: /Sign in to explore/ })).toHaveAttribute("href", "/login");

    rendered.unmount();
    renderExplorer(true);

    expect(screen.getByRole("link", { name: /Configure providers/ })).toHaveAttribute(
      "href",
      "/settings/ai-providers",
    );

  });

  it("changes example organization and role without using real account data", async () => {
    const user = userEvent.setup();
    renderExplorer();

    await user.selectOptions(screen.getByRole("combobox", { name: "Example organization" }), "horizon");
    expect(screen.getByText("Research brief.pdf")).toBeInTheDocument();
    expect(screen.getAllByText("Horizon Research").length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByRole("combobox", { name: "Example role" }), "member");
    expect(screen.getByText("Illustrative restricted administrator capability")).toBeInTheDocument();
    expect(screen.getByText(/no permissions change here/)).toBeInTheDocument();
  });
});
