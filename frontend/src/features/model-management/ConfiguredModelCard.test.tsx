import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  deleteConfiguredModel: vi.fn(),
  setConfiguredModelEnabled: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { NexusApiError } from "../../services/api/error";
import { ConfiguredModelCard } from "./ConfiguredModelCard";
import type { ConfiguredModel } from "./types";

const model: ConfiguredModel = {
  publicId: "11111111-1111-4111-8111-111111111111",
  providerPublicId: "22222222-2222-4222-8222-222222222222",
  providerType: "openai",
  providerModelName: "gpt-5",
  displayName: "GPT-5",
  modelType: "chat",
  capabilities: ["streaming"],
  embeddingDimension: null,
  enabled: true,
};

function renderCard(
  overrides: Partial<ConfiguredModel> = {},
  providerReady = true,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConfiguredModelCard
        model={{ ...model, ...overrides }}
        defaultTypes={["chat"]}
        canManage
        providerReady={providerReady}
        providerReadinessMessage="Provider is not ready."
      />
    </QueryClientProvider>,
  );
}

describe("ConfiguredModelCard", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    apiMocks.setConfiguredModelEnabled.mockResolvedValue({});
    apiMocks.deleteConfiguredModel.mockResolvedValue(undefined);
  });

  it("allows disabling even when the provider is no longer ready", async () => {
    const user = userEvent.setup();
    renderCard({}, false);

    await user.click(screen.getByRole("button", { name: "Disable" }));

    expect(apiMocks.setConfiguredModelEnabled).toHaveBeenCalledWith(
      model.publicId,
      false,
    );
  });

  it("blocks enabling when the provider is visibly ineligible", () => {
    renderCard({ enabled: false }, false);

    expect(screen.getByRole("button", { name: "Enable" })).toBeDisabled();
    expect(screen.getByText("Provider is not ready.")).toBeVisible();
  });

  it("confirms deletion and maps conflicts to safe feedback", async () => {
    const user = userEvent.setup();
    apiMocks.deleteConfiguredModel.mockRejectedValue(
      new NexusApiError("database detail", 409, "CONFLICT"),
    );
    renderCard();

    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove model" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This model cannot be removed while it is still in use.",
    );
    expect(screen.queryByText("database detail")).not.toBeInTheDocument();
  });
});
