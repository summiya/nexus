import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const providerApi = vi.hoisted(() => ({
  getModelProviderCapabilities: vi.fn(),
  listConfiguredProviders: vi.fn(),
}));
const modelApi = vi.hoisted(() => ({
  getModelDefaults: vi.fn(),
  listConfiguredModels: vi.fn(),
}));

vi.mock("../model-providers/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../model-providers/api")>()),
  ...providerApi,
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...modelApi,
}));

import { AIModelsSettings } from "./AIModelsSettings";
import type { ConfiguredModel } from "./types";
import type { ConfiguredProvider } from "../model-providers";

const firstProviderId = "11111111-1111-4111-8111-111111111111";
const secondProviderId = "22222222-2222-4222-8222-222222222222";
const modelId = "33333333-3333-4333-8333-333333333333";

function provider(
  publicId: string,
  displayName: string,
  overrides: Partial<ConfiguredProvider> = {},
): ConfiguredProvider {
  return {
    publicId,
    providerType: "openai",
    displayName,
    settings: {},
    enabled: true,
    credentialConfigured: true,
    validationStatus: "valid",
    lastValidatedAt: "2026-09-30T00:00:00Z",
    ...overrides,
  };
}

function model(overrides: Partial<ConfiguredModel> = {}): ConfiguredModel {
  return {
    publicId: modelId,
    providerPublicId: firstProviderId,
    providerType: "openai",
    providerModelName: "gpt-5",
    displayName: "GPT-5",
    modelType: "chat",
    capabilities: ["streaming", "tools"],
    embeddingDimension: null,
    enabled: true,
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AIModelsSettings />
    </QueryClientProvider>,
  );
}

describe("AIModelsSettings", () => {
  beforeEach(() => {
    Object.values(providerApi).forEach((mock) => mock.mockReset());
    Object.values(modelApi).forEach((mock) => mock.mockReset());
    providerApi.getModelProviderCapabilities.mockResolvedValue({
      canRead: true,
      canManage: true,
    });
    providerApi.listConfiguredProviders.mockResolvedValue([
      provider(firstProviderId, "OpenAI production"),
      provider(secondProviderId, "OpenAI research"),
    ]);
    modelApi.listConfiguredModels.mockResolvedValue([model()]);
    modelApi.getModelDefaults.mockResolvedValue({
      chat: modelId,
      embedding: null,
      reranker: null,
    });
  });

  it("groups models by provider instance and shows providers with zero models", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "AI Models" }),
    ).toBeInTheDocument();
    const production = screen
      .getByRole("heading", { name: "OpenAI production" })
      .closest("section");
    const research = screen
      .getByRole("heading", { name: "OpenAI research" })
      .closest("section");
    expect(production).not.toBeNull();
    expect(research).not.toBeNull();
    expect(
      within(production as HTMLElement).getByRole("heading", { name: "GPT-5" }),
    ).toBeInTheDocument();
    expect(
      within(research as HTMLElement).getByText("No configured models."),
    ).toBeVisible();
  });

  it("shows model metadata and organization default state", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "GPT-5" });
    expect(screen.getByText("Streaming")).toBeVisible();
    expect(screen.getByText("Tools")).toBeVisible();
    expect(screen.getByText("Default chat")).toBeVisible();
    expect(
      screen.getByRole("combobox", { name: "Default Chat Model" }),
    ).toHaveValue(modelId);
  });

  it("does not load organization model data without read capability", async () => {
    providerApi.getModelProviderCapabilities.mockResolvedValue({
      canRead: false,
      canManage: false,
    });

    renderPage();

    expect(
      await screen.findByText(
        "You do not have permission to view AI model configuration.",
      ),
    ).toBeVisible();
    expect(providerApi.listConfiguredProviders).not.toHaveBeenCalled();
    expect(modelApi.listConfiguredModels).not.toHaveBeenCalled();
    expect(modelApi.getModelDefaults).not.toHaveBeenCalled();
  });

  it("renders configuration read-only without manage capability", async () => {
    providerApi.getModelProviderCapabilities.mockResolvedValue({
      canRead: true,
      canManage: false,
    });

    renderPage();

    await screen.findByRole("heading", { name: "GPT-5" });
    expect(
      screen.queryByRole("button", { name: "Discover models" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Disable" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Default Chat Model" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("GPT-5", { selector: "p" })).toBeVisible();
  });

  it("fails safely when separately loaded model data is inconsistent", async () => {
    modelApi.listConfiguredModels.mockResolvedValue([
      model({ providerPublicId: "99999999-9999-4999-8999-999999999999" }),
    ]);

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "AI model configuration is temporarily unavailable.",
    );
  });
});
