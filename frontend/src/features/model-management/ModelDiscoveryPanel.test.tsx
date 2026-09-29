import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  discoverProviderModels: vi.fn(),
  registerModels: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { NexusApiError } from "../../services/api/error";
import { ModelDiscoveryPanel } from "./ModelDiscoveryPanel";
import type { ConfiguredModel } from "./types";

const providerId = "11111111-1111-4111-8111-111111111111";
const providerRevision = "2026-09-30T00:00:00Z";
const configured: ConfiguredModel = {
  publicId: "22222222-2222-4222-8222-222222222222",
  providerPublicId: providerId,
  providerType: "openai",
  providerModelName: "already-configured",
  displayName: "Existing",
  modelType: "chat",
  capabilities: ["streaming"],
  embeddingDimension: null,
  enabled: true,
};

function renderPanel(
  providerReady = true,
  configuredModels: readonly ConfiguredModel[] = [configured],
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = (models: readonly ConfiguredModel[]) => (
    <QueryClientProvider client={client}>
      <ModelDiscoveryPanel
        providerPublicId={providerId}
        providerRevision={providerRevision}
        configuredModels={models}
        providerReady={providerReady}
        providerReadinessMessage="Provider is not ready."
      />
    </QueryClientProvider>
  );
  const rendered = render(view(configuredModels));
  return {
    ...rendered,
    rerenderWithModels: (models: readonly ConfiguredModel[]) =>
      rendered.rerender(view(models)),
  };
}

describe("ModelDiscoveryPanel", () => {
  beforeEach(() => {
    apiMocks.discoverProviderModels.mockReset();
    apiMocks.registerModels.mockReset();
    apiMocks.discoverProviderModels.mockResolvedValue([
      {
        providerModelName: "already-configured",
        displayName: "Existing",
        modelType: "chat",
        capabilities: ["streaming"],
        embeddingDimension: null,
      },
      {
        providerModelName: "new-chat",
        displayName: "New Chat",
        modelType: "chat",
        capabilities: ["streaming", "tools"],
        embeddingDimension: null,
      },
      {
        providerModelName: "new-embedding",
        displayName: "New Embedding",
        modelType: "embedding",
        capabilities: [],
        embeddingDimension: 1024,
      },
      {
        providerModelName: "unknown-embedding",
        displayName: "Unknown Embedding",
        modelType: "embedding",
        capabilities: [],
        embeddingDimension: null,
      },
    ]);
    apiMocks.registerModels.mockResolvedValue([]);
  });

  it("discovers, filters, selects, and batch-registers candidates", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Discover models" }));
    expect(await screen.findByText("New Chat")).toBeVisible();
    expect(screen.queryByText("Existing")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Unknown Embedding/)).toBeDisabled();

    await user.click(screen.getByLabelText(/New Chat/));
    await user.click(screen.getByLabelText(/New Embedding/));
    await user.click(
      screen.getByRole("button", { name: "Register selected (2)" }),
    );

    expect(apiMocks.registerModels).toHaveBeenCalledWith(providerId, {
      registrationMode: "discovered",
      providerModelNames: ["new-chat", "new-embedding"],
    });
  });

  it("drops stale selections that are no longer visible candidates", async () => {
    const user = userEvent.setup();
    const { rerenderWithModels } = renderPanel();

    await user.click(screen.getByRole("button", { name: "Discover models" }));
    await user.click(await screen.findByLabelText(/New Chat/));

    const nowConfigured: ConfiguredModel = {
      ...configured,
      publicId: "66666666-6666-4666-8666-666666666666",
      providerModelName: "new-chat",
      displayName: "New Chat",
    };
    rerenderWithModels([configured, nowConfigured]);

    expect(screen.queryByLabelText(/New Chat/)).not.toBeInTheDocument();
    await user.click(screen.getByLabelText(/New Embedding/));
    await user.click(
      screen.getByRole("button", { name: "Register selected (1)" }),
    );

    expect(apiMocks.registerModels).toHaveBeenCalledWith(providerId, {
      registrationMode: "discovered",
      providerModelNames: ["new-embedding"],
    });
  });

  it("blocks discovery when the provider is visibly ineligible", () => {
    renderPanel(false);

    expect(
      screen.getByRole("button", { name: "Discover models" }),
    ).toBeDisabled();
    expect(screen.getByText("Provider is not ready.")).toBeVisible();
    expect(apiMocks.discoverProviderModels).not.toHaveBeenCalled();
  });

  it("shows safe rate-limit feedback with explicit retry", async () => {
    const user = userEvent.setup();
    apiMocks.discoverProviderModels.mockRejectedValue(
      new NexusApiError("raw detail", 429, "RATE_LIMITED"),
    );
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Discover models" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many discovery attempts. Try again later.",
    );
    expect(screen.queryByText("raw detail")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
  });
});
