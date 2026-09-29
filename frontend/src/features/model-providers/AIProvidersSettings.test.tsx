import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  createProvider: vi.fn(),
  deleteProvider: vi.fn(),
  getModelProviderCapabilities: vi.fn(),
  listConfiguredProviders: vi.fn(),
  listProviderCatalog: vi.fn(),
  setProviderCredential: vi.fn(),
  setProviderEnabled: vi.fn(),
  updateProvider: vi.fn(),
  validateProvider: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

import { AIProvidersSettings } from "./AIProvidersSettings";
import type { ConfiguredProvider, ProviderCatalogItem } from "./types";

const providerId = "11111111-1111-4111-8111-111111111111";
const secondProviderId = "22222222-2222-4222-8222-222222222222";

const catalog: ProviderCatalogItem[] = [
  { providerType: "openai", displayName: "OpenAI", requiredSettings: [] },
  {
    providerType: "anthropic",
    displayName: "Anthropic",
    requiredSettings: [],
  },
  {
    providerType: "azure_openai",
    displayName: "Azure OpenAI",
    requiredSettings: ["endpoint", "api_version"],
  },
  { providerType: "gemini", displayName: "Gemini", requiredSettings: [] },
  {
    providerType: "openai_compatible",
    displayName: "OpenAI-compatible",
    requiredSettings: ["base_url"],
  },
];

function provider(publicId: string, displayName: string): ConfiguredProvider {
  return {
    publicId,
    providerType: "openai",
    displayName,
    settings: {},
    enabled: false,
    credentialConfigured: false,
    validationStatus: "unvalidated",
    lastValidatedAt: null,
  };
}

function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderSettings() {
  const client = createClient();
  return render(
    <QueryClientProvider client={client}>
      <AIProvidersSettings />
    </QueryClientProvider>,
  );
}

describe("AIProvidersSettings", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    apiMocks.getModelProviderCapabilities.mockResolvedValue({
      canRead: true,
      canManage: true,
    });
    apiMocks.listProviderCatalog.mockResolvedValue(catalog);
    apiMocks.listConfiguredProviders.mockResolvedValue([]);
  });

  it("shows every catalog provider and preserves multiple configured instances", async () => {
    apiMocks.listConfiguredProviders.mockResolvedValue([
      provider(providerId, "OpenAI production"),
      provider(secondProviderId, "OpenAI research"),
    ]);

    renderSettings();

    expect(
      await screen.findByRole("heading", { name: "AI Providers" }),
    ).toBeInTheDocument();
    for (const item of catalog) {
      expect(
        screen.getByRole("heading", { name: item.displayName }),
      ).toBeInTheDocument();
    }
    expect(
      screen.getByRole("heading", { name: "OpenAI production" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "OpenAI research" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 configured")).toBeInTheDocument();
  });

  it("does not request provider data without read capability", async () => {
    apiMocks.getModelProviderCapabilities.mockResolvedValue({
      canRead: false,
      canManage: false,
    });

    renderSettings();

    expect(
      await screen.findByText(
        "You do not have permission to view AI provider configuration.",
      ),
    ).toBeInTheDocument();
    expect(apiMocks.listProviderCatalog).not.toHaveBeenCalled();
    expect(apiMocks.listConfiguredProviders).not.toHaveBeenCalled();
  });

  it("renders provider state read-only without manage capability", async () => {
    apiMocks.getModelProviderCapabilities.mockResolvedValue({
      canRead: true,
      canManage: false,
    });
    apiMocks.listConfiguredProviders.mockResolvedValue([
      provider(providerId, "OpenAI production"),
    ]);

    renderSettings();

    const card = (
      await screen.findByRole("heading", {
        name: "OpenAI production",
      })
    ).closest("article");
    expect(card).not.toBeNull();
    expect(
      within(card as HTMLElement).queryByRole("button"),
    ).not.toBeInTheDocument();
  });

  it("builds create fields from catalog requirements", async () => {
    const user = userEvent.setup();
    renderSettings();

    await screen.findByRole("heading", { name: "AI Providers" });
    const azureGroup = screen
      .getByRole("heading", { name: "Azure OpenAI" })
      .closest("section");
    expect(azureGroup).not.toBeNull();
    await user.click(
      within(azureGroup as HTMLElement).getByRole("button", {
        name: "Add configuration",
      }),
    );

    expect(
      within(azureGroup as HTMLElement).getByLabelText("Endpoint"),
    ).toBeInTheDocument();
    expect(
      within(azureGroup as HTMLElement).getByLabelText("API version"),
    ).toBeInTheDocument();
    expect(
      within(azureGroup as HTMLElement).queryByLabelText("Enabled"),
    ).not.toBeInTheDocument();
  });
});
