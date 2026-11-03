import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { setAuthStatus } from "../features/auth/store";
import { HomePage } from "./HomePage";

function renderLanding(showForAuthenticated = false) {
  return render(
    <MemoryRouter>
      <HomePage showForAuthenticated={showForAuthenticated} />
    </MemoryRouter>,
  );
}

describe("NEXUS public homepage", () => {
  beforeEach(() => {
    setAuthStatus("unauthenticated");
  });

  it("explains available capabilities separately from the RAG and agent roadmap", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: /every idea.*every model/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Knowledge that answers back" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Agents that do the work" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("In development").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Planned").length).toBeGreaterThan(0);
  });

  it("lets signed-in users revisit the public design through /explore", () => {
    setAuthStatus("authenticated");
    renderLanding(true);

    expect(
      screen.getByRole("link", { name: /Open workspace/i }),
    ).toHaveAttribute("href", "/conversations");
  });

  it("switches preview views and sample models without calling an API", async () => {
    const user = userEvent.setup();
    renderLanding();

    const preview = screen.getByLabelText("Interactive NEXUS product preview");
    await user.click(
      within(preview).getByRole("button", { name: /AI models/ }),
    );
    await user.click(
      within(preview).getByRole("button", { name: /^GPT/i }),
    );
    await user.click(within(preview).getByRole("button", { name: /New chat/ }));

    expect(
      within(preview).getByRole("combobox", { name: "Demo AI model" }),
    ).toHaveValue("gpt");
  });

  it("uses sample prompts and labels the generated answer as simulated", async () => {
    const user = userEvent.setup();
    renderLanding();

    await user.click(
      screen.getByRole("button", { name: /Plan a project/ }),
    );
    expect(screen.getByRole("textbox", { name: "Demo message" })).toHaveValue(
      "Plan a product launch.",
    );

    await user.click(screen.getByRole("button", { name: "Send demo message" }));
    expect(
      screen.getByText(/Claude Sonnet · simulated response/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Model responses are simulated/),
    ).toBeInTheDocument();
  });

  it("only selects a local file, without pretending to upload it", async () => {
    const user = userEvent.setup();
    renderLanding();

    const file = new File(["demo"], "project-notes.txt", {
      type: "text/plain",
    });
    await user.upload(screen.getByLabelText("Choose a sample file"), file);
    expect(screen.getByText(/project-notes.txt/)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Remove sample file" }),
    );
    expect(screen.queryByText(/project-notes.txt/)).not.toBeInTheDocument();
  });

  it("switches the journey details between RAG and planned agent execution", async () => {
    const user = userEvent.setup();
    renderLanding();

    expect(
      screen.getByRole("tabpanel", { name: "02 · Knowledge + RAG" }),
    ).toHaveTextContent("In development");
    await user.click(screen.getByRole("tab", { name: "03 · Agentic AI" }));
    expect(
      screen.getByRole("tabpanel", { name: "03 · Agentic AI" }),
    ).toHaveTextContent("Planned");
  });
});
