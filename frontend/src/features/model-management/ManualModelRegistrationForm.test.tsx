import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({ registerModels: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { ManualModelRegistrationForm } from "./ManualModelRegistrationForm";

const providerId = "11111111-1111-4111-8111-111111111111";

function renderForm(
  providerType: "azure_openai" | "openai_compatible" = "azure_openai",
  providerReady = true,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ManualModelRegistrationForm
        providerPublicId={providerId}
        providerType={providerType}
        providerReady={providerReady}
        providerReadinessMessage="Provider is not ready."
      />
    </QueryClientProvider>,
  );
}

describe("ManualModelRegistrationForm", () => {
  beforeEach(() => {
    apiMocks.registerModels.mockReset();
    apiMocks.registerModels.mockResolvedValue([]);
  });

  it("uses Azure deployment wording and registers declared chat metadata", async () => {
    const user = userEvent.setup();
    renderForm();

    await user.click(screen.getByRole("button", { name: "Add deployment" }));
    await user.type(
      screen.getByLabelText("Azure deployment name"),
      "chat-prod",
    );
    await user.type(screen.getByLabelText("Display name"), "Production Chat");
    await user.click(screen.getByLabelText("streaming"));
    await user.click(screen.getByLabelText("tools"));
    await user.click(screen.getByRole("button", { name: "Register model" }));

    expect(apiMocks.registerModels).toHaveBeenCalledWith(providerId, {
      registrationMode: "manual",
      providerModelName: "chat-prod",
      displayName: "Production Chat",
      modelType: "chat",
      capabilities: ["streaming", "tools"],
      embeddingDimension: null,
    });
  });

  it("requires a positive embedding dimension and sends no capabilities", async () => {
    const user = userEvent.setup();
    renderForm("openai_compatible");

    await user.click(screen.getByRole("button", { name: "Add model" }));
    await user.type(
      screen.getByLabelText("Provider model identifier"),
      "embed-v1",
    );
    await user.type(screen.getByLabelText("Display name"), "Embedding V1");
    await user.selectOptions(screen.getByLabelText("Model type"), "embedding");
    await user.type(screen.getByLabelText("Embedding dimension"), "0");
    await user.click(screen.getByRole("button", { name: "Register model" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a positive whole-number dimension.",
    );
    expect(apiMocks.registerModels).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Embedding dimension"));
    await user.type(screen.getByLabelText("Embedding dimension"), "1536");
    await user.click(screen.getByRole("button", { name: "Register model" }));
    expect(apiMocks.registerModels).toHaveBeenCalledWith(
      providerId,
      expect.objectContaining({
        modelType: "embedding",
        capabilities: [],
        embeddingDimension: 1536,
      }),
    );
  });

  it("renders reranker without capability or dimension controls", async () => {
    const user = userEvent.setup();
    renderForm("openai_compatible");

    await user.click(screen.getByRole("button", { name: "Add model" }));
    await user.selectOptions(screen.getByLabelText("Model type"), "reranker");

    expect(
      screen.queryByRole("group", { name: "Capabilities" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Embedding dimension"),
    ).not.toBeInTheDocument();
  });

  it("blocks manual registration when the provider is visibly ineligible", () => {
    renderForm("azure_openai", false);

    expect(
      screen.getByRole("button", { name: "Add deployment" }),
    ).toBeDisabled();
    expect(screen.getByText("Provider is not ready.")).toBeVisible();
  });
});
