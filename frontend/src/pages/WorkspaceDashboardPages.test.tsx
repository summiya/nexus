import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../features/conversations/queries", () => ({
  useConversationsQuery: () => ({
    data: [
      {
        publicId: "11111111-1111-4111-8111-111111111111",
        title: "Architecture discussion",
        createdAt: "2026-11-01T00:00:00Z",
        updatedAt: "2026-11-03T00:00:00Z",
      },
    ],
    isPending: false,
    isError: false,
  }),
}));

import {
  WorkspaceConceptPage,
  WorkspaceOverviewPage,
} from "./WorkspaceDashboardPages";

describe("Workspace dashboard design", () => {
  it("shows a dashboard with real recent conversations and useful destinations", () => {
    render(
      <MemoryRouter>
        <WorkspaceOverviewPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Good to have you here." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Architecture discussion/ })).toHaveAttribute(
      "href",
      "/conversations/11111111-1111-4111-8111-111111111111",
    );
    expect(screen.getByRole("link", { name: /Knowledge bases/ })).toHaveAttribute(
      "href",
      "/knowledge-bases",
    );
  });

  it("filters and inspects project designs without creating server-side resources", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <WorkspaceConceptPage section="projects" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument();
    const filter = screen.getByRole("textbox", { name: "Filter projects" });
    await user.type(filter, "engineering");

    const list = screen.getByRole("region", { name: "Projects list" });
    expect(within(list).getByRole("button", { name: /Engineering hub/ })).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: /Product launch/ })).toBeNull();

    await user.clear(filter);
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    await user.click(screen.getByRole("tab", { name: "Context" }));
    expect(screen.getByRole("tabpanel", { name: "Context" })).toHaveTextContent(
      "Connect the right conversations",
    );

    await user.click(screen.getByRole("button", { name: /New project/ }));
    expect(screen.getByRole("status")).toHaveTextContent("preview only");
  });

  it("provides accessible design previews for incidents and MCP integrations", () => {
    const { rerender } = render(
      <MemoryRouter>
        <WorkspaceConceptPage section="incidents" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Incidents" })).toBeInTheDocument();
    expect(screen.getByText("Latency investigation")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <WorkspaceConceptPage section="tools" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "MCP & tools" })).toBeInTheDocument();
    expect(screen.getByText("Custom MCP server")).toBeInTheDocument();
    expect(screen.getByText(/No live tools or records are changed/)).toBeInTheDocument();
  });
});
