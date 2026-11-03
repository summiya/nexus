import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { NexusWorkspacePreview } from "./NexusWorkspacePreview";

function renderPreview() {
  render(<NexusWorkspacePreview />);
  return screen.getByLabelText("Interactive NEXUS product preview");
}

describe("NEXUS interactive homepage workspace preview", () => {
  it("displays recent conversations above the workspace sections and opens a sample thread", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    const sidebar = within(preview).getByRole("complementary", {
      name: "Preview navigation",
    });
    expect(
      within(sidebar).getByText("RECENT CONVERSATIONS"),
    ).toBeInTheDocument();
    expect(within(sidebar).getByText("WORKSPACE")).toBeInTheDocument();
    const recent = within(preview).getByRole("navigation", {
      name: "Sample recent conversations",
    });
    await user.click(
      within(recent).getByRole("button", {
        name: /Q4 product launch strategy/,
      }),
    );

    const messages = within(preview).getByLabelText(
      "Sample conversation history",
    );
    expect(
      within(messages).getByText(/Help me organize our Q4 product launch/),
    ).toBeInTheDocument();

    await user.click(within(preview).getByRole("button", { name: /New chat/ }));
    expect(
      within(preview).getByRole("heading", { name: /Where should we begin/ }),
    ).toBeInTheDocument();
  });

  it("opens the projects view and creates a local example project", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    await user.click(
      within(preview).getByRole("button", { name: /^Projects/i }),
    );
    expect(
      within(preview).getByRole("heading", { name: "Projects" }),
    ).toBeInTheDocument();
    await user.click(
      within(preview).getByRole("button", { name: /New project/ }),
    );
    expect(
      within(preview).getByText(/A sample project was created/),
    ).toBeInTheDocument();
    expect(
      within(preview).getByText("New project", { selector: "strong" }),
    ).toBeInTheDocument();
  });

  it("switches artifacts and previews their content without leaving the page", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    await user.click(
      within(preview).getByRole("button", { name: /^Artifacts$/i }),
    );
    expect(
      within(preview).getByRole("heading", { name: "Artifacts" }),
    ).toBeInTheDocument();
    await user.click(
      within(preview).getByRole("button", { name: /API example/ }),
    );
    expect(
      within(preview).getByText(/async function generateSummary/),
    ).toBeInTheDocument();

    await user.click(
      within(preview).getByRole("button", { name: /Create artifact/ }),
    );
    expect(
      within(preview).getByText(/A sample artifact was added/),
    ).toBeInTheDocument();
  });

  it("supports illustrative MCP connector switches and connection filters", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    await user.click(
      within(preview).getByRole("button", { name: /Tools & MCP/ }),
    );
    expect(
      within(preview).getByRole("heading", { name: "Tools & MCP" }),
    ).toBeInTheDocument();
    await user.click(
      within(preview).getByRole("button", {
        name: "Enable Workspace MCP demo connector",
      }),
    );
    expect(
      within(preview).getByRole("button", {
        name: "Disable Workspace MCP demo connector",
      }),
    ).toHaveAttribute("aria-pressed", "true");

    await user.click(within(preview).getByRole("button", { name: "Enabled" }));
    expect(within(preview).queryByText("Google Drive")).not.toBeInTheDocument();
    expect(within(preview).getByText("Workspace MCP")).toBeInTheDocument();
    expect(
      within(preview).getByText(/No third-party connection is created/),
    ).toBeInTheDocument();
  });

  it("steps through an agent workflow with a sample human approval", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    await user.click(
      within(preview).getByRole("button", { name: /^Agents$/i }),
    );
    await user.click(
      within(preview).getByRole("button", { name: /Start sample workflow/ }),
    );
    await user.click(
      within(preview).getByRole("button", { name: /Continue demo/ }),
    );
    expect(
      within(preview).getByText(/ready for human review/),
    ).toBeInTheDocument();
    await user.click(
      within(preview).getByRole("button", { name: /Approve sample step/ }),
    );
    await user.click(
      within(preview).getByRole("button", { name: /Continue demo/ }),
    );
    expect(
      within(preview).getByText(/Sample workflow complete/),
    ).toBeInTheDocument();
  });

  it("shares model selection with the composer and sends a simulated response", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    await user.click(
      within(preview).getByRole("button", { name: /AI models/ }),
    );
    await user.click(
      within(preview).getByRole("button", { name: /GPT OpenAI/ }),
    );
    await user.click(
      within(preview).getByRole("button", { name: /Continue in sample chat/ }),
    );
    expect(
      within(preview).getByRole("combobox", { name: "Demo AI model" }),
    ).toHaveValue("gpt");

    await user.click(
      within(preview).getByRole("button", { name: /Plan a project/ }),
    );
    await user.click(
      within(preview).getByRole("button", { name: "Send demo message" }),
    );
    expect(
      within(preview).getByText(/GPT · simulated response/),
    ).toBeInTheDocument();
    expect(
      within(preview).getByRole("navigation", {
        name: "Sample recent conversations",
      }),
    ).toHaveTextContent("Plan a product launch");
  });

  it("keeps user-selected files local and allows removing the sample attachment", async () => {
    const user = userEvent.setup();
    const preview = renderPreview();

    await user.upload(
      within(preview).getByLabelText("Choose a sample file"),
      new File(["demo"], "brief.txt", { type: "text/plain" }),
    );
    expect(within(preview).getByText(/brief.txt/)).toBeInTheDocument();
    await user.click(
      within(preview).getByRole("button", { name: "Remove sample file" }),
    );
    expect(within(preview).queryByText(/brief.txt/)).not.toBeInTheDocument();

    await user.click(within(preview).getByRole("button", { name: /^Files$/i }));
    expect(within(preview).getByText("brief.txt")).toBeInTheDocument();
    expect(
      within(preview).getByText(
        /Files selected in this preview stay in your browser/,
      ),
    ).toBeInTheDocument();
  });
});
