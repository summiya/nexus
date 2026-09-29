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

import { ProviderCard } from "./ProviderCard";
import type { ConfiguredProvider, ProviderCatalogItem } from "./types";

const providerId = "11111111-1111-4111-8111-111111111111";
const catalogItem: ProviderCatalogItem = {
  providerType: "openai_compatible",
  displayName: "OpenAI-compatible",
  requiredSettings: ["base_url"],
};

function provider(
  overrides: Partial<ConfiguredProvider> = {},
): ConfiguredProvider {
  return {
    publicId: providerId,
    providerType: "openai_compatible",
    displayName: "Private inference",
    settings: { base_url: "https://models.example.com/v1" },
    enabled: false,
    credentialConfigured: false,
    validationStatus: "unvalidated",
    lastValidatedAt: null,
    ...overrides,
  };
}

function renderCard(value = provider()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <ProviderCard catalogItem={catalogItem} provider={value} canManage />
      </QueryClientProvider>,
    ),
  };
}

describe("ProviderCard", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
  });

  it.each([
    ["valid", "Valid"],
    ["invalid_credentials", "Invalid credentials"],
    ["unreachable", "Provider unreachable"],
    ["unsupported_configuration", "Unsupported configuration"],
  ] as const)("renders %s validation state", (status, label) => {
    renderCard(
      provider({
        validationStatus: status,
        lastValidatedAt: "2026-09-29T23:14:00+04:00",
      }),
    );

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(/Sep 29, 2026/)).toBeInTheDocument();
  });

  it("submits only a changed display name", async () => {
    const user = userEvent.setup();
    apiMocks.updateProvider.mockResolvedValue(
      provider({ displayName: "Renamed" }),
    );
    renderCard();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const displayName = screen.getByLabelText("Display name");
    await user.clear(displayName);
    await user.type(displayName, "Renamed");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiMocks.updateProvider).toHaveBeenCalledWith(providerId, {
      displayName: "Renamed",
    });
  });

  it("warns that changing a provider URL clears an existing credential", async () => {
    const user = userEvent.setup();
    renderCard(provider({ credentialConfigured: true }));

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.type(screen.getByLabelText("Base URL"), "/changed");

    expect(
      screen.getByText(
        /Changing this provider URL removes its stored credential/,
      ),
    ).toBeInTheDocument();
  });

  it("clears credential plaintext from the UI after a successful save", async () => {
    const user = userEvent.setup();
    apiMocks.setProviderCredential.mockResolvedValue(undefined);
    renderCard();

    await user.click(screen.getByRole("button", { name: "Add credential" }));
    const input = screen.getByLabelText("Provider credential");
    await user.type(input, "distinctive-secret-value");
    const credentialForm = input.closest("form");
    expect(credentialForm).not.toBeNull();
    await user.click(
      within(credentialForm as HTMLFormElement).getByRole("button", {
        name: "Add credential",
      }),
    );

    expect(apiMocks.setProviderCredential).toHaveBeenCalledWith(
      providerId,
      "distinctive-secret-value",
    );
    expect(
      screen.queryByDisplayValue("distinctive-secret-value"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("distinctive-secret-value"),
    ).not.toBeInTheDocument();
  });

  it("clears credential plaintext when credential entry is cancelled", async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole("button", { name: "Add credential" }));
    const input = screen.getByLabelText("Provider credential");
    await user.type(input, "credential-to-discard");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(apiMocks.setProviderCredential).not.toHaveBeenCalled();
    expect(
      screen.queryByDisplayValue("credential-to-discard"),
    ).not.toBeInTheDocument();
  });

  it("validates, toggles, and confirms deletion through separate actions", async () => {
    const user = userEvent.setup();
    apiMocks.validateProvider.mockResolvedValue({
      status: "valid",
      lastValidatedAt: "2026-09-29T23:14:00+04:00",
    });
    apiMocks.setProviderEnabled.mockResolvedValue(provider({ enabled: true }));
    apiMocks.deleteProvider.mockResolvedValue(undefined);
    renderCard();

    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(apiMocks.validateProvider).toHaveBeenCalledWith(providerId);

    await user.click(screen.getByRole("button", { name: "Enable" }));
    expect(apiMocks.setProviderEnabled).toHaveBeenCalledWith(providerId, true);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    const confirmation = screen.getByRole("group", {
      name: "Confirm provider removal",
    });
    expect(
      within(confirmation).queryByText(/recoverable/i),
    ).not.toBeInTheDocument();
    await user.click(
      within(confirmation).getByRole("button", { name: "Remove provider" }),
    );
    expect(apiMocks.deleteProvider).toHaveBeenCalledWith(providerId);
  });
});
